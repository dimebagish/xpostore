import os
import base64
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, g
from api.supa import supabase, admin_client
import smtplib
from email.message import EmailMessage
import random
import string
from math import isfinite

# -------------------------
# CONFIG
# -------------------------
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', '')
APP_EMAIL = os.environ.get('SMTP_EMAIL', '')
APP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
PREVIEW_TTL = timedelta(hours=2)
PREVIEW_LOGO_MAX_BYTES = 256 * 1024
PREVIEW_BUSINESS_TYPES = ('Clothing store', 'Mobile store', 'Accessories store', 'Other')
LOCAL_PREVIEWS = {}
_preview_supabase = None

CLIENT_DIR = os.path.join(os.path.dirname(__file__), 'client')
with open(os.path.join(CLIENT_DIR, 'store.json'), encoding='utf-8') as store_file:
    STORE_CONFIG = json.load(store_file)
ADVANCE_PAYMENT_PERCENT = float(STORE_CONFIG.get('advance_payment_percent', 20))
if not 0 <= ADVANCE_PAYMENT_PERCENT <= 100:
    raise ValueError('advance_payment_percent must be between 0 and 100')

BOOK_WINDOW_MINUTES = 5
PK_TZ = timezone(timedelta(hours=5))  # Pakistan Standard Time

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
    static_folder=os.path.join(os.path.dirname(__file__), 'static')
)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret')


# -------------------------
# HELPERS
# -------------------------
def send_email(subject, body, receipt=None, to_email=None, html=False):
    subject = customize_email_content(subject)
    body = customize_email_content(body)
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = f"{STORE_CONFIG['business_name']} <{os.environ.get('STORE_EMAIL', APP_EMAIL)}>"
    msg['To'] = to_email or ADMIN_EMAIL   # fallback to admin if not specified
    if html:
        msg.set_content('This email is best viewed in an HTML-compatible email client.')
        msg.add_alternative(body, subtype='html')
    else:
        msg.set_content(body)

    if receipt:
        file_data = receipt.read()
        receipt.seek(0)
        msg.add_attachment(file_data,
                           maintype='image',
                           subtype='jpeg',
                           filename=receipt.filename)

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(APP_EMAIL, APP_PASSWORD)
        smtp.send_message(msg)


def customize_email_content(content):
    content = content.replace('BibiJan Creations', STORE_CONFIG['business_name'])
    content = content.replace('BIBIJAN CREATIONS', STORE_CONFIG['business_name'].upper())
    content = content.replace('20%', f'{ADVANCE_PAYMENT_PERCENT:g}%')
    content = content.replace('Rs ', f"{STORE_CONFIG['currency_symbol']} ")
    content = content.replace('Age:', f"{STORE_CONFIG['variant_label']}:")
    email_logo_url = STORE_CONFIG.get('email_logo_url', '').strip()
    old_logo_url = 'https://bibijancreations.space/static/logo.png'
    if email_logo_url:
        content = content.replace(old_logo_url, email_logo_url)
    else:
        content = re.sub(
            r'<img\b(?=[^>]*src="https://bibijancreations\.space/static/logo\.png")[^>]*>',
            '', content, flags=re.IGNORECASE | re.DOTALL
        )
    return content


def upload_payment_receipt(receipt):
    if not receipt or not receipt.filename:
        raise ValueError('Please upload a screenshot of your bank transfer.')
    if receipt.mimetype not in {'image/jpeg', 'image/png', 'image/webp'}:
        raise ValueError('Upload a JPG, PNG, or WebP screenshot.')

    cloudinary_url = os.environ.get('CLOUDINARY_URL')
    if not cloudinary_url:
        raise RuntimeError('CLOUDINARY_URL is not configured')

    import cloudinary
    from cloudinary.uploader import upload

    cloudinary.config(secure=True)
    result = upload(
        receipt.stream,
        folder='payment-receipts',
        resource_type='image',
        unique_filename=True
    )
    receipt_url = result.get('secure_url')
    if not receipt_url:
        raise RuntimeError('Cloudinary did not return a secure receipt URL')
    return receipt_url


def upload_product_images(files):
    files = [file for file in files if file and file.filename]
    if not files:
        return []
    if not os.environ.get('CLOUDINARY_URL'):
        raise RuntimeError('CLOUDINARY_URL is not configured')

    allowed_types = {'image/jpeg', 'image/png', 'image/webp'}
    if any(file.mimetype not in allowed_types for file in files):
        raise ValueError('Upload JPG, PNG, or WebP product pictures.')

    import cloudinary
    from cloudinary.uploader import upload

    cloudinary.config(secure=True)
    urls = []
    for file in files:
        result = upload(
            file.stream,
            folder='products',
            resource_type='image',
            unique_filename=True
        )
        image_url = result.get('secure_url')
        if not image_url:
            raise RuntimeError('Cloudinary did not return a secure product image URL')
        urls.append(image_url)
    return urls


def parse_age_prices(form):
    ages = form.getlist('ages')
    prices = form.getlist('prices')
    if len(ages) != len(prices):
        raise ValueError(f"Add a {STORE_CONFIG['variant_label'].lower()} and price for every option.")

    age_prices = []
    seen_ages = set()
    for age, price in zip(ages, prices):
        age = age.strip()
        price = price.strip()
        if not age or not price:
            raise ValueError(f"Every {STORE_CONFIG['variant_label'].lower()} option needs both a label and a price.")
        try:
            amount = float(price)
        except ValueError as error:
            raise ValueError(f"Enter a valid price for every {STORE_CONFIG['variant_label'].lower()}.") from error
        if not isfinite(amount) or amount < 0:
            raise ValueError('Prices must be zero or greater.')
        if age.casefold() in seen_ages:
            raise ValueError(f"Each {STORE_CONFIG['variant_label'].lower()} option must be unique.")
        seen_ages.add(age.casefold())
        age_prices.append({'age': age, 'price': amount})

    if not age_prices:
        raise ValueError(f"Add at least one {STORE_CONFIG['variant_label'].lower()} and price.")
    return age_prices


def fetch_item_age_prices(item_id):
    return supabase.table('item_age_prices').select('age, price').eq('item_id', item_id).order('price').execute().data or []


def attach_item_age_prices(items):
    if not items:
        return items
    item_ids = [item['id'] for item in items]
    variants = supabase.table('item_age_prices').select('item_id, age, price').in_('item_id', item_ids).execute().data or []
    by_item = {item_id: [] for item_id in item_ids}
    for variant in variants:
        by_item[variant['item_id']].append(variant)
    for item in items:
        item['age_prices'] = sorted(by_item[item['id']], key=lambda variant: float(variant['price']))
    return items


def fetch_items(category=None, sort=None, search=None, filter_status=None):
    query = supabase.table('items').select('*')
    if filter_status:
        query = query.eq('status', filter_status)
    if category:
        query = query.eq('category', category)
    if search:
        query = query.ilike('model', f'%{search}%')
    if sort == 'price_asc':
        query = query.order('price', desc=False)
    elif sort == 'price_desc':
        query = query.order('price', desc=True)
    return query.execute().data or []


@app.context_processor
def inject_now():
    return {
        'now': datetime.now,
        'store': getattr(g, 'store_override', STORE_CONFIG),
        'preview_mode': getattr(g, 'preview_mode', False),
        'preview_flow': getattr(g, 'preview_mode', False) or request.endpoint in ('try_it_out', 'preview_store')
    }


@app.get('/client-assets/<path:filename>')
def client_asset(filename):
    return send_from_directory(os.path.join(CLIENT_DIR, 'assets'), filename)


def get_preview_supabase():
    global _preview_supabase
    preview_url = os.environ.get('PREVIEW_SUPABASE_URL')
    preview_key = os.environ.get('PREVIEW_SUPABASE_SERVICE_ROLE_KEY')
    if not preview_url and not preview_key:
        if os.environ.get('VERCEL'):
            raise RuntimeError('Configure the dedicated preview Supabase environment variables.')
        return None
    if not preview_url or not preview_key:
        raise RuntimeError('Both preview Supabase environment variables are required.')
    if _preview_supabase is None:
        from supabase import create_client
        _preview_supabase = create_client(preview_url, preview_key)
    return _preview_supabase


def cleanup_expired_previews():
    now = datetime.now(timezone.utc)
    preview_db = get_preview_supabase()
    if preview_db:
        preview_db.table('store_previews').delete().lte('expires_at', now.isoformat()).execute()
    else:
        expired = [
            preview_id for preview_id, record in LOCAL_PREVIEWS.items()
            if datetime.fromisoformat(record['expires_at']) <= now
        ]
        for preview_id in expired:
            LOCAL_PREVIEWS.pop(preview_id, None)


def save_preview(record):
    preview_db = get_preview_supabase()
    if preview_db:
        preview_db.table('store_previews').insert(record).execute()
    else:
        LOCAL_PREVIEWS[record['id']] = record


def load_preview(preview_id):
    if not preview_id:
        return None
    preview_db = get_preview_supabase()
    if preview_db:
        result = preview_db.table('store_previews').select('*').eq('id', preview_id).execute()
        records = result.data or []
        record = records[0] if records else None
    else:
        record = LOCAL_PREVIEWS.get(preview_id)
    if not record:
        return None
    expires_at = datetime.fromisoformat(record['expires_at'].replace('Z', '+00:00'))
    if expires_at <= datetime.now(timezone.utc):
        delete_preview(preview_id)
        return None
    return record


def delete_preview(preview_id):
    if not preview_id:
        return
    preview_db = get_preview_supabase()
    if preview_db:
        preview_db.table('store_previews').delete().eq('id', preview_id).execute()
    else:
        LOCAL_PREVIEWS.pop(preview_id, None)


def read_preview_logo(upload):
    if not upload or not upload.filename:
        return ''
    image_data = upload.stream.read(PREVIEW_LOGO_MAX_BYTES + 1)
    if len(image_data) > PREVIEW_LOGO_MAX_BYTES:
        raise ValueError('Choose a logo smaller than 256 KB.')
    signatures = {
        'image/png': image_data.startswith(b'\x89PNG\r\n\x1a\n'),
        'image/jpeg': image_data.startswith(b'\xff\xd8\xff'),
        'image/webp': image_data[:4] == b'RIFF' and image_data[8:12] == b'WEBP',
    }
    mime_type = upload.mimetype.lower()
    if not signatures.get(mime_type, False):
        raise ValueError('Upload a valid PNG, JPG, or WebP logo.')
    encoded = base64.b64encode(image_data).decode('ascii')
    return f'data:{mime_type};base64,{encoded}'


@app.route('/try-it-out', methods=['GET', 'POST'])
def try_it_out():
    if request.method == 'GET':
        values = load_preview(session.get('store_preview_id')) or {}
        return render_template(
            'preview_setup.html',
            business_types=PREVIEW_BUSINESS_TYPES,
            form_values=values
        )

    business_name = (request.form.get('business_name') or '').strip()
    business_type = (request.form.get('business_type') or '').strip()
    tagline = (request.form.get('tagline') or '').strip()
    if not business_name or len(business_name) > 80:
        flash('Enter a business name of 1 to 80 characters.', 'error')
    elif not tagline or len(tagline) > 140:
        flash('Enter a tagline of 1 to 140 characters.', 'error')
    elif business_type not in PREVIEW_BUSINESS_TYPES:
        flash('Choose a business type.', 'error')
    else:
        if business_type == 'Other':
            business_type = (request.form.get('other_business_type') or '').strip()
            if not business_type or len(business_type) > 40:
                flash('Enter your business type (up to 40 characters).', 'error')
                return render_template(
                    'preview_setup.html', business_types=PREVIEW_BUSINESS_TYPES,
                    form_values=request.form
                ), 400
        try:
            logo_data = read_preview_logo(request.files.get('logo'))
            cleanup_expired_previews()
        except ValueError as error:
            flash(str(error), 'error')
        except Exception:
            app.logger.exception('Preview storage is unavailable')
            flash('Store previews are temporarily unavailable. Please try again later.', 'error')
        else:
            preview_id = str(uuid.uuid4())
            expires_at = datetime.now(timezone.utc) + PREVIEW_TTL
            record = {
                'id': preview_id,
                'business_name': business_name,
                'business_type': business_type,
                'tagline': tagline,
                'logo_data': logo_data,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'expires_at': expires_at.isoformat(),
            }
            try:
                delete_preview(session.get('store_preview_id'))
                save_preview(record)
            except Exception:
                app.logger.exception('Preview creation failed')
                flash('Store previews are temporarily unavailable. Please try again later.', 'error')
            else:
                session['store_preview_id'] = preview_id
                session.permanent = True
                app.permanent_session_lifetime = PREVIEW_TTL
                return redirect(url_for('preview_store'))

    return render_template(
        'preview_setup.html', business_types=PREVIEW_BUSINESS_TYPES,
        form_values=request.form
    ), 400


@app.get('/try-it-out/store')
def preview_store():
    try:
        record = load_preview(session.get('store_preview_id'))
    except Exception:
        app.logger.exception('Preview lookup failed')
        record = None
    if not record:
        session.pop('store_preview_id', None)
        flash('Your preview expired. Enter your details to start another one.', 'info')
        return redirect(url_for('try_it_out'))

    store = dict(STORE_CONFIG)
    store.update({
        'business_name': record['business_name'],
        'business_type': record['business_type'],
        'headline': record['tagline'],
        'description': record['tagline'],
        'footer_tagline': record['tagline'],
        'logo': record['logo_data'],
        'website_url': '',
        'facebook_url': '',
        'instagram_url': '',
    })
    g.store_override = store
    g.preview_mode = True
    products = preview_products(record['business_type'])
    return render_template('preview_store.html', products=products)


def preview_products(business_type):
    samples = {
        'Clothing store': [
            ('Everyday Linen Shirt', 'photo-1521572163474-6864f9cf17ab', 5900, 'Sizes XS-XL'),
            ('Weekend Knitwear', 'photo-1434389677669-e08b4cac3105', 7400, 'Sizes S-XXL'),
            ('City Layer Jacket', 'photo-1483985988355-763728e1935b', 9800, 'Sizes XS-XL'),
        ],
        'Mobile store': [
            ('Nova X Smartphone', 'photo-1511707171634-5f897ff02aa9', 129900, '128 GB · 256 GB'),
            ('Everyday Wireless Earbuds', 'photo-1590658268037-6bf12165a8df', 18900, 'Black · White'),
            ('Protective Phone Case', 'photo-1601593346740-925612772716', 2500, 'Multiple models'),
        ],
        'Accessories store': [
            ('Structured Everyday Tote', 'photo-1548036328-c9fa89d128fa', 6900, 'Black · Tan · Olive'),
            ('Minimal Wristwatch', 'photo-1523275335684-37898b6baf30', 8900, 'Silver · Gold'),
            ('Studio Headphones', 'photo-1505740420928-5e560c06d30e', 12500, 'Black · Cream'),
        ],
        'Other': [
            ('Studio Favorite', 'photo-1542291026-7eec264c27ff', 3900, 'A customer favorite'),
            ('Everyday Essential', 'photo-1523275335684-37898b6baf30', 5900, 'Made for daily use'),
            ('The Signature Piece', 'photo-1548036328-c9fa89d128fa', 7900, 'Available in several colors'),
        ],
    }
    selected_samples = samples.get(business_type, samples['Other'])
    return [
        {
            'name': name,
            'price': price,
            'option_note': option_note,
            'image_url': f'https://images.unsplash.com/{image_id}?auto=format&fit=crop&w=800&q=82',
        }
        for name, image_id, price, option_note in selected_samples
    ]


@app.post('/try-it-out/exit')
def exit_preview():
    try:
        delete_preview(session.get('store_preview_id'))
    except Exception:
        app.logger.exception('Preview cleanup failed')
    session.pop('store_preview_id', None)
    return redirect(url_for('home'))


@app.template_filter('format_dt')
def format_datetime(value):
    """Format ISO datetime string to m/d/Y h:mm AM/PM"""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return value
    elif isinstance(value, datetime):
        dt = value
    else:
        return value

    try:
        # Works on Linux/Mac
        return dt.strftime("%-m/%-d/%Y %-I:%M %p")
    except ValueError:
        # Works on Windows
        return dt.strftime("%#m/%#d/%Y %#I:%M %p")


def parse_datetime_fields(records, fields=("booking_time","selling_time")):
    for p in records:
        for f in fields:
            if p.get(f) and isinstance(p[f], str):
                try:
                    p[f] = datetime.fromisoformat(p[f].replace("Z","+00:00"))
                except Exception:
                    pass
    return records

# -------------------------
# PUBLIC ROUTES
# -------------------------

# Customer checkout and payment submission
@app.route('/payment', methods=['GET', 'POST'])
def payment():
    if 'user_email' not in session:
        flash('You must be logged in to confirm payment.', 'error')
        return redirect(url_for('login'))

    item_ids = request.args.get("item_ids") or request.args.get("cart_ids")
    item_id = request.args.get("item_id")

    items, total_price, admin = [], 0, None

    # Single item
    if item_id:
        res = supabase.table("items").select("*, admin_id").eq("id", int(item_id)).single().execute()
        item = res.data
        if not item:
            flash("Item not found", "error")
            return redirect(url_for("home"))
        if item.get('status') != 'Available':
            flash('This item is not currently available.', 'error')
            return redirect(url_for('home'))

        age_prices = fetch_item_age_prices(item['id'])
        if age_prices:
            selected_age = request.values.get('age')
            selected_variant = next((variant for variant in age_prices if variant['age'] == selected_age), None)
            if not selected_variant:
                flash(f"Select a valid {STORE_CONFIG['variant_label'].lower()} before buying this item.", 'error')
                return redirect(url_for('item_detail', item_id=item['id']))
            item['selected_age'] = selected_variant['age']
            item['price'] = float(selected_variant['price'])
        else:
            item['selected_age'] = item.get('purchased_age')

        admin = supabase.table("admins").select("*").eq("id", item["admin_id"]).single().execute().data
        items = [item]
        total_price = float(item["price"])

    # Multiple items from cart
    elif item_ids:
        ids = [int(i) for i in item_ids.split(",") if i]
        res = supabase.table("items").select("*").in_("id", ids).execute()
        items = attach_item_age_prices(res.data or [])
        if any(item.get('status') != 'Available' for item in items):
            flash('One or more items in your cart are no longer available.', 'error')
            return redirect(url_for('view_cart'))
        cart_ages = session.get('cart_item_ages', session.get('cart_ages', {}))
        for item in items:
            if not item['age_prices']:
                continue
            selected_age = cart_ages.get(str(item['id']))
            selected_variant = next((variant for variant in item['age_prices'] if variant['age'] == selected_age), None)
            if not selected_variant:
                flash(f"Choose a {STORE_CONFIG['variant_label'].lower()} for each item with options before checkout.", 'error')
                return redirect(url_for('item_detail', item_id=item['id']))
            item['selected_age'] = selected_variant['age']
            item['price'] = float(selected_variant['price'])
        total_price = sum(float(item["price"]) for item in items if item.get("price"))

        # ⚠️ For now assume all cart items belong to the same admin
        if items:
            admin = supabase.table("admins").select("*").eq("id", items[0]["admin_id"]).single().execute().data

    advance_amount = round(total_price * ADVANCE_PAYMENT_PERCENT / 100, 2)
    delivery_balance = round(total_price - advance_amount, 2)

    # -------------------------
    # GET → Show payment page
    # -------------------------
    bank_details = {
        'bank_name': os.environ.get('PAYMENT_BANK_NAME', '').strip(),
        'account_name': os.environ.get('PAYMENT_ACCOUNT_NAME', '').strip(),
        'account_number': os.environ.get('PAYMENT_ACCOUNT_NUMBER', '').strip(),
        'iban': os.environ.get('PAYMENT_IBAN', '').strip(),
    }
    bank_details_configured = all(
        bank_details[key] for key in ('bank_name', 'account_name', 'account_number')
    )
    receipt_upload_configured = bool(os.environ.get('CLOUDINARY_URL'))

    if request.method == "GET":
        return render_template(
            "payment.html",
            items=items,
            total_price=total_price,
            advance_amount=advance_amount,
            delivery_balance=delivery_balance,
            admin=admin,
            bank_details=bank_details,
            bank_details_configured=bank_details_configured,
            receipt_upload_configured=receipt_upload_configured,
            advance_payment_percent=ADVANCE_PAYMENT_PERCENT
        )

    if not items:
        flash('Your order is empty.', 'error')
        return redirect(url_for('home'))

    buyer_name = (request.form.get('buyer_name') or '').strip()
    buyer_email = session['user_email'].strip()
    submitted_email = (request.form.get('buyer_email') or '').strip()
    buyer_phone = (request.form.get('buyer_phone') or '').strip()
    buyer_address = (request.form.get('buyer_address') or '').strip()
    receipt = request.files.get("receipt")
    if not all((buyer_name, buyer_email, buyer_phone, buyer_address)):
        flash('Complete your contact details before submitting payment.', 'error')
        return redirect(url_for('payment', item_id=item_id, item_ids=item_ids, age=request.values.get('age')))
    if submitted_email.casefold() != buyer_email.casefold():
        flash('Use the email address on your signed-in account for this order.', 'error')
        return redirect(url_for('payment', item_id=item_id, item_ids=item_ids, age=request.values.get('age')))

    try:
        receipt_url = upload_payment_receipt(receipt)
    except ValueError as error:
        flash(str(error), 'error')
        return redirect(url_for('payment', item_id=item_id, item_ids=item_ids, age=request.values.get('age')))
    except Exception:
        app.logger.exception('Payment receipt upload failed')
        flash('We could not upload your screenshot. Please try again.', 'error')
        return redirect(url_for('payment', item_id=item_id, item_ids=item_ids, age=request.values.get('age')))

    payment_method = 'Bank transfer'

    subject = f"New Payment Confirmation - {buyer_name}"
    body = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>New Payment Submission - BibiJan Creations</title>
</head>

<body style="
    margin: 0;
    padding: 0;
    background-color: #f7f1ec;
    font-family: Arial, Helvetica, sans-serif;
    color: #4a2636;
">

    <table width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background-color: #f7f1ec; padding: 35px 15px;">
        <tr>
            <td align="center">

                <table width="100%" cellpadding="0" cellspacing="0" border="0"
                       style="
                           max-width: 620px;
                           background-color: #fffdf9;
                           border-radius: 20px;
                           overflow: hidden;
                           box-shadow: 0 4px 20px rgba(74, 38, 54, 0.08);
                       ">

                    <!-- Header -->
                    <tr>
                        <td align="center"
                            style="
                                padding: 32px 25px 24px;
                                background-color: #fffaf5;
                                border-bottom: 1px solid #ead8d1;
                            ">

                            <img
                                src="https://bibijancreations.space/static/logo.png"
                                alt="BibiJan Creations"
                                width="180"
                                style="
                                    display: block;
                                    width: 180px;
                                    max-width: 70%;
                                    height: auto;
                                    border: 0;
                                "
                            >

                            <div style="
                                margin-top: 16px;
                                font-size: 13px;
                                letter-spacing: 2px;
                                color: #a86673;
                                text-transform: uppercase;
                            ">
                                Payment Review
                            </div>

                        </td>
                    </tr>


                    <!-- Alert -->
                    <tr>
                        <td style="padding: 35px 40px 20px;">

                            <div style="
                                display: inline-block;
                                padding: 7px 12px;
                                background-color: #f8eee9;
                                border-radius: 20px;
                                color: #a86673;
                                font-size: 11px;
                                font-weight: 700;
                                letter-spacing: 1px;
                                text-transform: uppercase;
                            ">
                                New Payment
                            </div>

                            <div style="
                                margin-top: 15px;
                                font-size: 27px;
                                line-height: 1.3;
                                font-weight: 600;
                                color: #4a2636;
                            ">
                                A customer has submitted a payment.
                            </div>

                            <div style="
                                margin-top: 10px;
                                font-size: 15px;
                                line-height: 1.7;
                                color: #6f5a62;
                            ">
                                Please review the payment details and proof below
                                and confirm the order once verified.
                            </div>

                        </td>
                    </tr>


                    <!-- Customer Information -->
                    <tr>
                        <td style="padding: 15px 40px 10px;">

                            <div style="
                                font-size: 12px;
                                font-weight: 700;
                                letter-spacing: 1.5px;
                                text-transform: uppercase;
                                color: #a86673;
                                margin-bottom: 12px;
                            ">
                                Customer Information
                            </div>

                            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                                   style="
                                       background-color: #ffffff;
                                       border: 1px solid #eee1db;
                                       border-radius: 14px;
                                   ">

                                <tr>
                                    <td style="padding: 14px 18px; color: #806c73; font-size: 13px;">
                                        Name
                                    </td>
                                    <td style="padding: 14px 18px; color: #4a2636; font-size: 14px; font-weight: 600;">
                                        {buyer_name}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="padding: 14px 18px; color: #806c73; font-size: 13px;">
                                        Email
                                    </td>
                                    <td style="padding: 14px 18px; color: #4a2636; font-size: 14px;">
                                        {buyer_email}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="padding: 14px 18px; color: #806c73; font-size: 13px;">
                                        Phone
                                    </td>
                                    <td style="padding: 14px 18px; color: #4a2636; font-size: 14px;">
                                        {buyer_phone}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="padding: 14px 18px; color: #806c73; font-size: 13px; vertical-align: top;">
                                        Address
                                    </td>
                                    <td style="padding: 14px 18px; color: #4a2636; font-size: 14px; line-height: 1.5;">
                                        {buyer_address}
                                    </td>
                                </tr>

                            </table>

                        </td>
                    </tr>


                    <!-- Items -->
                    <tr>
                        <td style="padding: 25px 40px 10px;">

                            <div style="
                                font-size: 12px;
                                font-weight: 700;
                                letter-spacing: 1.5px;
                                text-transform: uppercase;
                                color: #a86673;
                                margin-bottom: 12px;
                            ">
                                Order Items
                            </div>

                            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                                   style="
                                       background-color: #fbf3ee;
                                       border: 1px solid #ead8d1;
                                       border-radius: 14px;
                                   ">

                                {
                                    "".join([
                                        f'''
                                        <tr>
                                            <td style="
                                                padding: 15px 18px;
                                                color: #4a2636;
                                                font-size: 14px;
                                                font-weight: 600;
                                                border-bottom: 1px solid #ead8d1;
                                            ">
                                                {p['model']}
                                                {
                                                    f'<div style="margin-top:4px; font-size:12px; font-weight:400; color:#806c73;">Age: {p["selected_age"]}</div>'
                                                    if p.get('selected_age') else ''
                                                }
                                            </td>

                                            <td align="right"
                                                style="
                                                    padding: 15px 18px;
                                                    color: #8e4d62;
                                                    font-size: 14px;
                                                    font-weight: 700;
                                                    border-bottom: 1px solid #ead8d1;
                                                ">
                                                Rs {p['price']}
                                            </td>
                                        </tr>
                                        '''
                                        for p in items
                                    ])
                                }

                                <tr>
                                    <td style="
                                        padding: 17px 18px;
                                        font-size: 15px;
                                        font-weight: 700;
                                        color: #4a2636;
                                    ">
                                        Total
                                    </td>

                                    <td align="right"
                                        style="
                                            padding: 17px 18px;
                                            font-size: 19px;
                                            font-weight: 700;
                                            color: #8e4d62;
                                        ">
                                        Rs {total_price}
                                    </td>
                                </tr>

                            </table>

                        </td>
                    </tr>


                    <!-- Payment Details -->
                    <tr>
                        <td style="padding: 25px 40px 10px;">

                            <div style="
                                font-size: 12px;
                                font-weight: 700;
                                letter-spacing: 1.5px;
                                text-transform: uppercase;
                                color: #a86673;
                                margin-bottom: 12px;
                            ">
                                Payment Details
                            </div>

                            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                                   style="
                                       background-color: #ffffff;
                                       border: 1px solid #eee1db;
                                       border-radius: 14px;
                                   ">

                                <tr>
                                    <td style="padding: 15px 18px; color: #806c73; font-size: 13px;">
                                        Payment Method
                                    </td>

                                    <td align="right"
                                        style="padding: 15px 18px; color: #4a2636; font-size: 14px; font-weight: 600;">
                                        {payment_method}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="
                                        padding: 15px 18px;
                                        color: #806c73;
                                        font-size: 13px;
                                        border-top: 1px solid #eee1db;
                                    ">
                                        Payment Status
                                    </td>

                                    <td align="right"
                                        style="
                                            padding: 15px 18px;
                                            color: #b4773f;
                                            font-size: 13px;
                                            font-weight: 700;
                                            border-top: 1px solid #eee1db;
                                        ">
                                        Pending Review
                                    </td>
                                </tr>

                            </table>

                        </td>
                    </tr>


                    <!-- Payment Proof -->
                    <tr>
                        <td style="padding: 25px 40px 35px;">

                            <div style="
                                font-size: 12px;
                                font-weight: 700;
                                letter-spacing: 1.5px;
                                text-transform: uppercase;
                                color: #a86673;
                                margin-bottom: 12px;
                            ">
                                Payment Proof
                            </div>

                            <div style="
                                padding: 20px;
                                background-color: #4a2636;
                                border-radius: 16px;
                                text-align: center;
                            ">

                                <div style="
                                    font-size: 14px;
                                    color: #ead8d1;
                                    margin-bottom: 15px;
                                ">
                                    Customer payment receipt
                                </div>

                                <a href="{receipt_url}"
                                   style="
                                       display: inline-block;
                                       padding: 11px 22px;
                                       background-color: #c98080;
                                       color: #ffffff;
                                       text-decoration: none;
                                       border-radius: 8px;
                                       font-size: 13px;
                                       font-weight: 700;
                                   ">
                                    View Payment Proof
                                </a>

                            </div>

                        </td>
                    </tr>


                    <!-- Footer -->
                    <tr>
                        <td align="center"
                            style="
                                padding: 20px;
                                background-color: #4a2636;
                            ">

                            <div style="
                                font-size: 11px;
                                letter-spacing: 1px;
                                color: #ead8d1;
                            ">
                                BIBIJAN CREATIONS
                            </div>

                            <div style="
                                margin-top: 7px;
                                font-size: 11px;
                                color: #c9aeb5;
                            ">
                                Payment notification
                            </div>

                        </td>
                    </tr>

                </table>

            </td>
        </tr>
    </table>

</body>
</html>
"""

    customer_body = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Payment Received - BibiJan Creations</title>
</head>

<body style="
    margin: 0;
    padding: 0;
    background-color: #f7f1ec;
    font-family: Arial, Helvetica, sans-serif;
    color: #4a2636;
">

    <table width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background-color: #f7f1ec; padding: 35px 15px;">
        <tr>
            <td align="center">

                <table width="100%" cellpadding="0" cellspacing="0" border="0"
                       style="
                           max-width: 620px;
                           background-color: #fffdf9;
                           border-radius: 20px;
                           overflow: hidden;
                           box-shadow: 0 4px 20px rgba(74, 38, 54, 0.08);
                       ">

                    <!-- Header -->
                    <tr>
                        <td align="center"
                            style="
                                padding: 32px 25px 24px;
                                background-color: #fffaf5;
                                border-bottom: 1px solid #ead8d1;
                            ">

                            <img
                                src="https://bibijancreations.space/static/logo.png"
                                alt="BibiJan Creations"
                                width="180"
                                style="
                                    display: block;
                                    width: 180px;
                                    max-width: 70%;
                                    height: auto;
                                    border: 0;
                                "
                            >

                            <div style="
                                margin-top: 16px;
                                font-size: 13px;
                                letter-spacing: 2px;
                                color: #a86673;
                                text-transform: uppercase;
                            ">
                                Payment Received
                            </div>

                        </td>
                    </tr>


                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 35px 40px 20px;">

                            <div style="
                                font-size: 27px;
                                line-height: 1.3;
                                font-weight: 600;
                                color: #4a2636;
                                margin-bottom: 12px;
                            ">
                                Thank you, {buyer_name}! ♡
                            </div>

                            <div style="
                                font-size: 15px;
                                line-height: 1.7;
                                color: #6f5a62;
                            ">
                                We've received your order and payment submission.
                                Our team will review the payment and confirm your
                                order shortly.
                            </div>

                        </td>
                    </tr>


                    <!-- Pending Status -->
                    <tr>
                        <td style="padding: 10px 40px 20px;">

                            <div style="
                                padding: 21px;
                                background-color: #f8eee9;
                                border: 1px solid #ead8d1;
                                border-radius: 16px;
                                text-align: center;
                            ">

                                <div style="
                                    font-size: 27px;
                                    margin-bottom: 8px;
                                ">
                                    ⏳
                                </div>

                                <div style="
                                    font-size: 12px;
                                    letter-spacing: 1.5px;
                                    text-transform: uppercase;
                                    color: #a86673;
                                    font-weight: 700;
                                ">
                                    Payment Status
                                </div>

                                <div style="
                                    margin-top: 7px;
                                    font-size: 20px;
                                    font-weight: 700;
                                    color: #b4773f;
                                ">
                                    Pending Verification
                                </div>

                                <div style="
                                    margin-top: 7px;
                                    font-size: 13px;
                                    line-height: 1.5;
                                    color: #806c73;
                                ">
                                    Your payment is being reviewed by our team.
                                </div>

                            </div>

                        </td>
                    </tr>


                    <!-- Order Summary -->
                    <tr>
                        <td style="padding: 10px 40px;">

                            <div style="
                                font-size: 12px;
                                font-weight: 700;
                                letter-spacing: 1.5px;
                                text-transform: uppercase;
                                color: #a86673;
                                margin-bottom: 12px;
                            ">
                                Order Summary
                            </div>

                            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                                   style="
                                       background-color: #fbf3ee;
                                       border: 1px solid #ead8d1;
                                       border-radius: 14px;
                                   ">

                                {
                                    "".join([
                                        f'''
                                        <tr>
                                            <td style="
                                                padding: 15px 18px;
                                                color: #4a2636;
                                                font-size: 14px;
                                                font-weight: 600;
                                                border-bottom: 1px solid #ead8d1;
                                            ">
                                                {p['model']}
                                                {
                                                    f'<div style="margin-top:4px; font-size:12px; font-weight:400; color:#806c73;">Age: {p["selected_age"]}</div>'
                                                    if p.get('selected_age') else ''
                                                }
                                            </td>

                                            <td align="right"
                                                style="
                                                    padding: 15px 18px;
                                                    color: #8e4d62;
                                                    font-size: 14px;
                                                    font-weight: 700;
                                                    border-bottom: 1px solid #ead8d1;
                                                ">
                                                Rs {p['price']}
                                            </td>
                                        </tr>
                                        '''
                                        for p in items
                                    ])
                                }

                                <tr>
                                    <td style="
                                        padding: 17px 18px;
                                        color: #4a2636;
                                        font-size: 15px;
                                        font-weight: 700;
                                    ">
                                        Order Total
                                    </td>

                                    <td align="right"
                                        style="
                                            padding: 17px 18px;
                                            color: #8e4d62;
                                            font-size: 19px;
                                            font-weight: 700;
                                        ">
                                        Rs {total_price:.2f}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="padding: 14px 18px; color: #4a2636; font-size: 14px; font-weight: 700; border-top: 1px solid #ead8d1;">
                                        20% Advance Payable at Submission
                                    </td>
                                    <td align="right" style="padding: 14px 18px; color: #8e4d62; font-size: 16px; font-weight: 700; border-top: 1px solid #ead8d1;">
                                        Rs {advance_amount:.2f}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="padding: 14px 18px 17px; color: #4a2636; font-size: 14px; font-weight: 700; border-top: 1px solid #ead8d1;">
                                        Remaining Balance Due on Delivery
                                    </td>
                                    <td align="right" style="padding: 14px 18px 17px; color: #8e4d62; font-size: 16px; font-weight: 700; border-top: 1px solid #ead8d1;">
                                        Rs {delivery_balance:.2f}
                                    </td>
                                </tr>

                            </table>

                        </td>
                    </tr>


                    <!-- Buyer Information -->
                    <tr>
                        <td style="padding: 25px 40px 10px;">

                            <div style="
                                font-size: 12px;
                                font-weight: 700;
                                letter-spacing: 1.5px;
                                text-transform: uppercase;
                                color: #a86673;
                                margin-bottom: 12px;
                            ">
                                Delivery Information
                            </div>

                            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                                   style="
                                       background-color: #ffffff;
                                       border: 1px solid #eee1db;
                                       border-radius: 14px;
                                   ">

                                <tr>
                                    <td style="padding: 14px 18px; color: #806c73; font-size: 13px;">
                                        Name
                                    </td>

                                    <td style="padding: 14px 18px; color: #4a2636; font-size: 14px;">
                                        {buyer_name}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="padding: 14px 18px; color: #806c73; font-size: 13px;">
                                        Phone
                                    </td>

                                    <td style="padding: 14px 18px; color: #4a2636; font-size: 14px;">
                                        {buyer_phone}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="
                                        padding: 14px 18px;
                                        color: #806c73;
                                        font-size: 13px;
                                        vertical-align: top;
                                    ">
                                        Address
                                    </td>

                                    <td style="
                                        padding: 14px 18px;
                                        color: #4a2636;
                                        font-size: 14px;
                                        line-height: 1.5;
                                    ">
                                        {buyer_address}
                                    </td>
                                </tr>

                            </table>

                        </td>
                    </tr>


                    <!-- Payment Information -->
                    <tr>
                        <td style="padding: 25px 40px 10px;">

                            <div style="
                                font-size: 12px;
                                font-weight: 700;
                                letter-spacing: 1.5px;
                                text-transform: uppercase;
                                color: #a86673;
                                margin-bottom: 12px;
                            ">
                                Payment Details
                            </div>

                            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                                   style="
                                       background-color: #ffffff;
                                       border: 1px solid #eee1db;
                                       border-radius: 14px;
                                   ">

                                <tr>
                                    <td style="padding: 14px 18px; color: #806c73; font-size: 13px;">
                                        Payment Method
                                    </td>

                                    <td align="right"
                                        style="
                                            padding: 14px 18px;
                                            color: #4a2636;
                                            font-size: 14px;
                                            font-weight: 600;
                                        ">
                                        {payment_method}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="
                                        padding: 14px 18px;
                                        color: #806c73;
                                        font-size: 13px;
                                        border-top: 1px solid #eee1db;
                                    ">
                                        Status
                                    </td>

                                    <td align="right"
                                        style="
                                            padding: 14px 18px;
                                            color: #b4773f;
                                            font-size: 13px;
                                            font-weight: 700;
                                            border-top: 1px solid #eee1db;
                                        ">
                                        Awaiting Confirmation
                                    </td>
                                </tr>

                            </table>

                        </td>
                    </tr>


                    <!-- Closing -->
                    <tr>
                        <td style="
                            padding: 30px 40px 38px;
                            text-align: center;
                        ">

                            <div style="
                                font-size: 14px;
                                line-height: 1.7;
                                color: #6f5a62;
                            ">
                                We'll notify you as soon as your payment has
                                been verified and your order is confirmed.
                            </div>

                            <div style="
                                margin-top: 25px;
                                font-size: 15px;
                                font-weight: 600;
                                color: #4a2636;
                            ">
                                Thank you for shopping with us ♡
                            </div>

                            <div style="
                                margin-top: 6px;
                                font-size: 18px;
                                font-weight: 700;
                                color: #8e4d62;
                            ">
                                BibiJan Creations
                            </div>

                        </td>
                    </tr>


                    <!-- Footer -->
                    <tr>
                        <td align="center"
                            style="
                                padding: 20px;
                                background-color: #4a2636;
                            ">

                            <div style="
                                font-size: 11px;
                                letter-spacing: 1px;
                                color: #ead8d1;
                            ">
                                BIBIJAN CREATIONS
                            </div>

                            <div style="
                                margin-top: 7px;
                                font-size: 11px;
                                color: #c9aeb5;
                            ">
                                Made with love ♡
                            </div>

                        </td>
                    </tr>

                </table>

            </td>
        </tr>
    </table>

</body>
</html>
"""

    try:
        order_rows = []
        purchase_time = datetime.now(timezone.utc).isoformat()
        for item in items:
            order_rows.append({
                'item_id': item['id'],
                'model': item['model'],
                'specs': item.get('specs'),
                'condition': item.get('condition'),
                'category': item.get('category'),
                'admin_id': item.get('admin_id'),
                'price': item['price'],
                'status': 'Booked',
                'payment_status': 'Pending',
                'full_payment': False,
                'shipping_status': 'Pending',
                'buyer_name': buyer_name,
                'buyer_email': buyer_email,
                'buyer_phone': buyer_phone,
                'buyer_address': buyer_address,
                'payment_method': payment_method,
                'payment_receipt_url': receipt_url,
                'booking_time': purchase_time,
                'purchase_time': purchase_time,
                'purchased_age': item.get('selected_age'),
            })
        if order_rows:
            supabase.table('orders').insert(order_rows).execute()
    except Exception:
        app.logger.exception('Payment order update failed')
        flash('Your order could not be submitted. Please contact the store before retrying.', 'error')
        return redirect(url_for('payment', item_id=item_id, item_ids=item_ids, age=request.values.get('age')))

    try:
        send_email(subject, body, to_email=admin['email'] if admin else ADMIN_EMAIL, html=True)
        send_email('Order Received', customer_body, to_email=buyer_email, html=True)
    except Exception:
        app.logger.exception('Payment confirmation email failed')

    flash(STORE_CONFIG['order_confirmation_message'], 'ok')
    return redirect(url_for("account_purchased"))


@app.get('/')
def home():
    category = request.args.get('category')
    sort = request.args.get('sort')
    search = request.args.get('search')
    categories = sorted({item['cat_name'] for item in supabase.table('categories').select('cat_name').execute().data or []})
    items = attach_item_age_prices(fetch_items(category=category, sort=sort, search=search, filter_status='Available'))
    for item in items:
        item['media'] = supabase.table('item_media').select('*').eq('item_id', item['id']).execute().data
    return render_template('home.html', items=items, categories=categories)


@app.get('/item/<int:item_id>')
def item_detail(item_id):
    item = supabase.table('items').select('*').eq('id', item_id).single().execute().data
    if not item:
        flash('Item not found', 'error')
        return redirect(url_for('home'))

    media = supabase.table('item_media').select('*').eq('item_id', item_id).execute().data
    age_prices = fetch_item_age_prices(item_id)

    remaining_ms, deadline_iso = 0, None
    if item['status'] == 'Booked' and item.get('booking_time'):
        bt = datetime.fromisoformat(item['booking_time'].replace('Z', '+00:00'))
        deadline = bt + timedelta(minutes=BOOK_WINDOW_MINUTES)
        now = datetime.now(timezone.utc)
        if deadline > now:
            remaining_ms = int((deadline - now).total_seconds() * 1000)
            deadline_iso = deadline.isoformat()

    return render_template('item_detail.html', item=item, media=media, age_prices=age_prices,
                           remaining_ms=remaining_ms, deadline_iso=deadline_iso)


# -------------------------
# AUTH
# -------------------------
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        phone_field = request.form.get('phone')
        address = request.form.get('address')

        try:
            existing = supabase.table("profiles").select("id").eq("email", email).maybe_single().execute()
        except Exception:
            app.logger.exception("Signup profile lookup failed")
            flash("We couldn't check your account right now. Please try again.", "danger")
            return redirect(url_for("signup"))

        if existing and existing.data:
            flash("Email already registered. Please log in.", "danger")
            return redirect(url_for("login"))

        try:
            supabase.table('profiles').insert({
                'email': email,
                'password': password,
                'phone': phone_field,
                'address': address,
                'role': 'customer'
            }).execute()
        except Exception:
            app.logger.exception("Signup profile creation failed")
            flash("We couldn't create your account right now. Please try again.", "danger")
            return redirect(url_for("signup"))

        flash('Account created successfully. Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        res = supabase.table('profiles').select('*').eq('email', email).maybe_single().execute()
        user = res.data
        if user and user['password'] == password:
            session['user_email'] = email
            flash('Logged in.', 'ok')
            return redirect(url_for('home'))

        flash('Invalid credentials.', 'error')

    return render_template('login.html')


@app.get('/logout')
def logout():
    session.clear()
    flash('Logged out.', 'ok')
    return redirect(url_for('home'))


@app.route("/reset", methods=["GET", "POST"])
def reset_password():
    if request.method == "GET":
        # Always reset state when user first visits reset page
        session["reset_step"] = "email"
        session.pop("reset_email", None)
        session.pop("reset_otp", None)

    step = session.get("reset_step", "email")

    if request.method == "POST":
        # STEP 1: User enters email → send OTP
        if step == "email":
            email = request.form.get("email")
            res = supabase.table("profiles").select("id").eq("email", email).single().execute()

            if res.data:
                # Generate OTP
                otp = "".join(random.choices(string.digits, k=6))
                session["reset_email"] = email
                session["reset_otp"] = otp
                session["reset_step"] = "otp"

                # Send OTP via email helper
                subject = "Your Password Reset OTP"
                body = f"Your OTP code is: {otp}\n\nThis code will expire in 10 minutes."
                send_email(subject, body, to_email=email)

                flash("OTP has been sent to your email", "info")
            else:
                flash("Email not found", "danger")

        # STEP 2: User enters OTP + new password
        elif step == "otp":
            otp = request.form.get("otp")
            new_password = request.form.get("new_password")
            email = session.get("reset_email")

            if otp == session.get("reset_otp"):
                # Lookup user ID from profiles
                profile = supabase.table("profiles").select("id").eq("email", email).single().execute()
                if profile.data:
                    # Just update password in profiles table
                    supabase.table("profiles").update({
                        "password": new_password
                    }).eq("email", email).execute()

                    flash("Password updated successfully. Please log in.", "success")


                    # Clear session state
                    session.pop("reset_email", None)
                    session.pop("reset_otp", None)
                    session["reset_step"] = "email"
                    return redirect(url_for("login"))
                else:
                    flash("User profile not found", "danger")
            else:
                flash("Invalid OTP", "danger")


    return render_template("reset.html", step=session.get("reset_step", "email"))


# -------------------------
# ACCOUNT
# -------------------------
@app.route('/account/booked')
def account_booked():
    if 'user_email' not in session:
        flash('You must be logged in to view your orders.', 'error')
        return redirect(url_for('login'))

    res = supabase.table('orders') \
        .select('*') \
        .eq('status', 'Booked') \
        .eq('buyer_email', session['user_email']) \
        .execute()

    orders = parse_datetime_fields(res.data or [])
    return render_template('account_booked.html', orders=orders)


@app.get('/account/purchased')
def account_purchased():
    if not session.get('user_email'):
        return redirect(url_for('login'))
    email = session['user_email']
    orders = supabase.table('orders').select('*') \
        .eq('buyer_email', email) \
        .in_('status', ['Booked', 'Sold']) \
        .execute().data or []
    orders = parse_datetime_fields(orders)

    return render_template('account_purchased.html', orders=orders)

# Initialize cart in session if not exists
def get_cart():
    if "cart" not in session:
        session["cart"] = []
    return session["cart"]

@app.route("/cart/add/<int:item_id>", methods=["POST"])

def add_to_cart(item_id):
    age_prices = fetch_item_age_prices(item_id)
    selected_age = request.form.get('age')
    if age_prices and not any(variant['age'] == selected_age for variant in age_prices):
        flash(f"Select a {STORE_CONFIG['variant_label'].lower()} before adding this item to your cart.", 'error')
        return redirect(url_for('item_detail', item_id=item_id))

    cart = get_cart()
    if item_id not in cart:
        cart.append(item_id)
        session["cart"] = cart
    cart_ages = session.get('cart_item_ages', session.get('cart_ages', {}))
    if age_prices:
        cart_ages[str(item_id)] = selected_age
    else:
        cart_ages.pop(str(item_id), None)
    session['cart_item_ages'] = cart_ages
    if request.form.get('buy_now'):
        return redirect(url_for('payment', item_id=item_id, age=selected_age))
    return redirect(url_for("view_cart"))

@app.route("/cart")
def view_cart():
    cart_ids = get_cart()
    if not cart_ids:
        items = []
        total_price = 0
    else:
        res = supabase.table("items").select("*").in_("id", cart_ids).execute()
        items = attach_item_age_prices(res.data or [])
        cart_ages = session.get('cart_item_ages', session.get('cart_ages', {}))
        for item in items:
            selected_age = cart_ages.get(str(item['id']))
            variant = next((option for option in item['age_prices'] if option['age'] == selected_age), None)
            if variant:
                item['selected_age'] = variant['age']
                item['price'] = float(variant['price'])
        # Calculate total
        total_price = sum(float(item["price"]) for item in items if "price" in item)

    return render_template("cart.html", items=items, total_price=total_price)


@app.route("/cart/clear", methods=["POST"])
def clear_cart():
    session.pop("cart", None)
    session.pop('cart_item_ages', None)
    session.pop('cart_ages', None)
    return redirect(url_for("view_cart"))



@app.route("/cart/checkout", methods=["POST"])
def checkout_cart():
    selected = request.form.getlist("selected_items")
    if not selected:
        flash("Please select at least one item.", "error")
        return redirect(url_for("view_cart"))

    selected_items = supabase.table('items').select('id').in_('id', selected).execute().data or []
    cart_ages = session.get('cart_item_ages', session.get('cart_ages', {}))
    age_based = next((item for item in attach_item_age_prices(selected_items)
                      if item['age_prices'] and not any(
                          variant['age'] == cart_ages.get(str(item['id']))
                          for variant in item['age_prices']
                      )), None)
    if age_based:
        flash(f"Choose a {STORE_CONFIG['variant_label'].lower()} for each item with options before checkout.", 'error')
        return redirect(url_for('item_detail', item_id=age_based['id']))

    # Redirect to payment with selected IDs
    return redirect(url_for("payment", item_ids=",".join(selected)))


# -------------------------
# ADMIN AUTH
# -------------------------
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        identifier = request.form.get('identifier')  # could be email or username
        password = request.form.get('password')

        try:
            # Try to find by username OR email
            res = (
                supabase.table('admins')
                .select('*')
                .or_(f"username.eq.{identifier},email.eq.{identifier}")
                .maybe_single()
                .execute()
            )
        except Exception as e:
            flash('Database error: ' + str(e), 'error')
            return render_template('admin_login.html')

        admin = getattr(res, "data", None)

        if admin and admin.get('password') == password:
            session['is_admin'] = True
            session['admin_id'] = admin['id']
            session['admin_username'] = admin['username']
            flash(f'Welcome, {admin["username"]}!', 'ok')
            return redirect(url_for('admin_items'))
        else:
            flash('Invalid admin credentials', 'error')

    return render_template('admin_login.html')


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('admin_login'))
        return fn(*args, **kwargs)
    return wrapper

# -------------------------
# ADMIN ROUTES
# -------------------------

# Route for adding a new item
@app.route('/admin/items/new', methods=['GET', 'POST'])
@admin_required
def admin_item_new():
    categories = sorted({c['cat_name'] for c in supabase.table('categories').select('cat_name').execute().data})
    if request.method == 'POST':
        try:
            age_prices = parse_age_prices(request.form)
            uploaded_urls = upload_product_images(request.files.getlist('media_files'))
        except ValueError as error:
            flash(str(error), 'error')
            age_prices = [{'age': age, 'price': price} for age, price in zip(request.form.getlist('ages'), request.form.getlist('prices'))]
            media = [{'url': url} for url in request.form.get('media', '').splitlines() if url.strip()]
            return render_template('admin_item_form.html', categories=categories, item=None, media=media, age_prices=age_prices)
        except Exception:
            app.logger.exception('Product image upload failed')
            flash('We could not upload the product pictures. Please try again.', 'error')
            age_prices = [{'age': age, 'price': price} for age, price in zip(request.form.getlist('ages'), request.form.getlist('prices'))]
            media = [{'url': url} for url in request.form.get('media', '').splitlines() if url.strip()]
            return render_template('admin_item_form.html', categories=categories, item=None, media=media, age_prices=age_prices)

        item_result = supabase.table('items').insert({
            'model': request.form['model'].strip(),
            'price': min(variant['price'] for variant in age_prices),
            'status': 'Available',
            'category': request.form['category'],
            'admin_id': session['admin_id']
        }).execute()
        item_id = item_result.data[0]['id']
        supabase.table('item_age_prices').insert([
            {'item_id': item_id, **variant} for variant in age_prices
        ]).execute()
        media_urls = [url.strip() for url in request.form.get('media', '').splitlines() if url.strip()]
        media_urls.extend(uploaded_urls)
        if media_urls:
            supabase.table('item_media').insert([
                {'item_id': item_id, 'url': url, 'kind': 'image'} for url in media_urls
            ]).execute()
        flash('Item added successfully!', 'ok')
        return redirect(url_for('admin_items'))

    return render_template('admin_item_form.html', categories=categories, item=None, media=[], age_prices=[])

# Route for editing an existing item
@app.route('/admin/items/<int:item_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_item_edit(item_id):

    item = supabase.table('items').select('*').eq('id', item_id).single().execute().data
    if not item:
        flash('Item not found', 'error')
        return redirect(url_for('admin_items'))

    categories = sorted({c['cat_name'] for c in supabase.table('categories').select('cat_name').execute().data})
    if request.method == 'POST':
        try:
            age_prices = parse_age_prices(request.form)
            uploaded_urls = upload_product_images(request.files.getlist('media_files'))
        except ValueError as error:
            flash(str(error), 'error')
            age_prices = [{'age': age, 'price': price} for age, price in zip(request.form.getlist('ages'), request.form.getlist('prices'))]
            media = [{'url': url} for url in request.form.get('media', '').splitlines() if url.strip()]
            return render_template('admin_item_form.html', categories=categories, item=item, media=media, age_prices=age_prices)
        except Exception:
            app.logger.exception('Product image upload failed')
            flash('We could not upload the product pictures. Please try again.', 'error')
            age_prices = [{'age': age, 'price': price} for age, price in zip(request.form.getlist('ages'), request.form.getlist('prices'))]
            media = [{'url': url} for url in request.form.get('media', '').splitlines() if url.strip()]
            return render_template('admin_item_form.html', categories=categories, item=item, media=media, age_prices=age_prices)

        supabase.table('items').update({
            'model': request.form['model'].strip(),
            'category': request.form['category'],
            'price': min(variant['price'] for variant in age_prices)
        }).eq('id', item_id).execute()
        supabase.table('item_age_prices').delete().eq('item_id', item_id).execute()
        supabase.table('item_age_prices').insert([
            {'item_id': item_id, **variant} for variant in age_prices
        ]).execute()

        media_urls = [url.strip() for url in request.form.get('media', '').splitlines() if url.strip()]
        media_urls.extend(uploaded_urls)
        supabase.table('item_media').delete().eq('item_id', item_id).execute()
        if media_urls:
            supabase.table('item_media').insert([
                {'item_id': item_id, 'url': url, 'kind': 'image'} for url in media_urls
            ]).execute()
        flash('Item updated successfully!', 'ok')
        return redirect(url_for('admin_items'))
       
    media = supabase.table('item_media').select('*').eq('item_id', item_id).execute().data
    age_prices = fetch_item_age_prices(item_id)
    return render_template('admin_item_form.html', item=item, media=media, categories=categories, age_prices=age_prices)

# Route for reviewing orders (payment verification)
@app.route('/admin/review', methods=['GET', 'POST'])
@admin_required
def admin_review():
    order_id = request.args.get('order_id')
    order = None
    
    if order_id:
        order = supabase.table('orders').select('*').eq('id', order_id).single().execute().data
    
    # Get all pending bookings
    pending = supabase.table('orders').select('*').eq('status', 'Booked').order('booking_time', desc=True).execute().data
    
    return render_template('admin_review.html', order=order, pending=pending)


# Route for verifying payments from review page
@app.route('/admin/review/verify/<int:order_id>', methods=['POST'])
@admin_required
def admin_review_verify(order_id):
    action = request.form.get('action')
    order = supabase.table('orders').select('*').eq('id', order_id).single().execute().data

    if not order:
        flash('Order not found.', 'error')
        return redirect(url_for('admin_review'))

    if action == 'full':
        if order.get('status') != 'Booked':
            flash('Only booked orders can be verified.', 'error')
            return redirect(url_for('admin_review'))
        if order.get('payment_method') == 'Bank transfer' and not order.get('payment_receipt_url'):
            flash('A payment screenshot is required before verifying this transfer.', 'error')
            return redirect(url_for('admin_review', order_id=order_id))
        now = datetime.now(timezone.utc).isoformat()
        supabase.table('orders').update({
            'payment_status': 'Full paid',
            'full_payment': True,
            'status': 'Sold',
            'selling_time': now,
            'shipping_status': 'Pending'
        }).eq('id', order_id).execute()
        flash('Full payment verified and order marked as sold!', 'ok')
        
    elif action == 'revert':
        if order.get('status') == 'Sold':
            flash('Sold items cannot be reverted to available.', 'error')
            return redirect(url_for('admin_review'))
        if order.get('status') != 'Booked':
            flash('Only booked orders can be cancelled.', 'error')
            return redirect(url_for('admin_review'))
        supabase.table('orders').update({
            'status': 'Cancelled',
            'payment_status': 'Cancelled'
        }).eq('id', order_id).execute()
        flash('Order cancelled. The product remains available in inventory.', 'ok')
    
    return redirect(url_for('admin_review'))

@app.get('/admin/items')
@admin_required
def admin_items():
    items = supabase.table('items').select('*').eq('admin_id', session['admin_id']).execute().data or []
    orders = supabase.table('orders').select('item_id,status,shipping_status').eq('admin_id', session['admin_id']).execute().data or []
    order_counts = {}
    for order in orders:
        item_id = order.get('item_id')
        counts = order_counts.setdefault(item_id, {
            'booked_orders': 0,
            'sold_orders': 0,
            'shipped_orders': 0,
        })
        if order.get('status') == 'Booked':
            counts['booked_orders'] += 1
        elif order.get('status') == 'Sold' and order.get('shipping_status') == 'Shipped':
            counts['shipped_orders'] += 1
        elif order.get('status') == 'Sold':
            counts['sold_orders'] += 1

    for item in items:
        item.update(order_counts.get(item['id'], {
            'booked_orders': 0,
            'sold_orders': 0,
            'shipped_orders': 0,
        }))
    return render_template('admin_items.html', items=items)

@app.post('/admin/orders/<int:order_id>/full')
@admin_required
def mark_full_payment(order_id):
    result = supabase.table('orders').select('*').eq('id', order_id).maybe_single().execute()
    order = result.data if result else None
    if not order:
        flash('Order not found.', 'error')
        return redirect(url_for('admin_bookings'))
    if order.get('status') != 'Booked':
        flash('Only booked orders can be marked fully paid.', 'error')
        return redirect(url_for('admin_bookings'))
    if order.get('payment_method') == 'Bank transfer' and not order.get('payment_receipt_url'):
        flash('A payment screenshot is required before verifying this transfer.', 'error')
        return redirect(url_for('admin_review', order_id=order_id))

    now = datetime.now(timezone.utc).isoformat()
    supabase.table("orders").update({
        "payment_status": "Full paid",
        "full_payment": True,
        "status": "Sold",
        "selling_time": now,
        "shipping_status": "Pending"
    }).eq("id", order_id).execute()

    order = supabase.table("orders").select("*").eq("id", order_id).single().execute().data

    # ✅ Build the invoice-style email body here
    subject = f"Order Confirmation - Item Purchase #{order['id']}"
    body = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Order Confirmed - BibiJan Creations</title>
</head>

<body style="
    margin: 0;
    padding: 0;
    background-color: #f7f1ec;
    font-family: Arial, Helvetica, sans-serif;
    color: #4a2636;
">

    <table width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background-color: #f7f1ec; padding: 35px 15px;">
        <tr>
            <td align="center">

                <!-- Main Container -->
                <table width="100%" cellpadding="0" cellspacing="0" border="0"
                       style="
                           max-width: 620px;
                           background-color: #fffdf9;
                           border-radius: 20px;
                           overflow: hidden;
                           box-shadow: 0 4px 20px rgba(74, 38, 54, 0.08);
                       ">

                    <!-- Header -->
                    <tr>
                        <td align="center"
                            style="
                                padding: 32px 25px 24px;
                                background-color: #fffaf5;
                                border-bottom: 1px solid #ead8d1;
                            ">

                            <img
                                src="https://bibijancreations.space/static/logo.png"
                                alt="BibiJan Creations"
                                width="180"
                                style="
                                    display: block;
                                    width: 180px;
                                    max-width: 70%;
                                    height: auto;
                                    border: 0;
                                "
                            >

                            <div style="
                                margin-top: 16px;
                                font-size: 13px;
                                letter-spacing: 2px;
                                color: #a86673;
                                text-transform: uppercase;
                            ">
                                Order Confirmation
                            </div>

                        </td>
                    </tr>


                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 35px 40px 15px;">

                            <div style="
                                font-size: 27px;
                                line-height: 1.3;
                                font-weight: 600;
                                color: #4a2636;
                                margin-bottom: 12px;
                            ">
                                Thank you, {order.get('buyer_name', 'Customer')}! ♡
                            </div>

                            <div style="
                                font-size: 15px;
                                line-height: 1.7;
                                color: #6f5a62;
                            ">
                                Your purchase has been successfully confirmed and
                                your order has been marked as fully paid.
                                We're so happy to have you shop with us.
                            </div>

                        </td>
                    </tr>


                    <!-- Order Summary -->
                    <tr>
                        <td style="padding: 20px 40px 10px;">

                            <div style="
                                font-size: 12px;
                                font-weight: 700;
                                letter-spacing: 1.5px;
                                text-transform: uppercase;
                                color: #a86673;
                                margin-bottom: 12px;
                            ">
                                Order Summary
                            </div>

                            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                                   style="
                                       background-color: #fbf3ee;
                                       border: 1px solid #ead8d1;
                                       border-radius: 14px;
                                       overflow: hidden;
                                   ">

                                <tr>
                                    <td style="padding: 15px 18px; color: #806c73; font-size: 14px;">
                                        Model
                                    </td>
                                    <td align="right"
                                        style="padding: 15px 18px; color: #4a2636; font-size: 14px; font-weight: 600;">
                                        {order['model']}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="padding: 13px 18px; color: #806c73; font-size: 14px;">
                                        Age
                                    </td>
                                    <td align="right"
                                        style="padding: 13px 18px; color: #4a2636; font-size: 14px;">
                                        {order.get('purchased_age') or 'N/A'}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="padding: 13px 18px; color: #806c73; font-size: 14px;">
                                        Condition
                                    </td>
                                    <td align="right"
                                        style="padding: 13px 18px; color: #4a2636; font-size: 14px;">
                                        {order['condition']}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="
                                        padding: 16px 18px;
                                        color: #4a2636;
                                        font-size: 15px;
                                        font-weight: 700;
                                        border-top: 1px solid #ead8d1;
                                    ">
                                        Total Paid
                                    </td>
                                    <td align="right"
                                        style="
                                            padding: 16px 18px;
                                            color: #8e4d62;
                                            font-size: 18px;
                                            font-weight: 700;
                                            border-top: 1px solid #ead8d1;
                                        ">
                                        Rs {order['price']}
                                    </td>
                                </tr>

                            </table>

                        </td>
                    </tr>


                    <!-- Buyer Information -->
                    <tr>
                        <td style="padding: 25px 40px 10px;">

                            <div style="
                                font-size: 12px;
                                font-weight: 700;
                                letter-spacing: 1.5px;
                                text-transform: uppercase;
                                color: #a86673;
                                margin-bottom: 12px;
                            ">
                                Your Information
                            </div>

                            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                                   style="
                                       background-color: #ffffff;
                                       border: 1px solid #eee1db;
                                       border-radius: 14px;
                                   ">

                                <tr>
                                    <td style="padding: 14px 18px; color: #806c73; font-size: 13px; width: 35%;">
                                        Name
                                    </td>
                                    <td style="padding: 14px 18px; color: #4a2636; font-size: 14px;">
                                        {order.get('buyer_name')}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="padding: 14px 18px; color: #806c73; font-size: 13px;">
                                        Email
                                    </td>
                                    <td style="padding: 14px 18px; color: #4a2636; font-size: 14px;">
                                        {order.get('buyer_email')}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="padding: 14px 18px; color: #806c73; font-size: 13px;">
                                        Phone
                                    </td>
                                    <td style="padding: 14px 18px; color: #4a2636; font-size: 14px;">
                                        {order.get('buyer_phone')}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="padding: 14px 18px; color: #806c73; font-size: 13px; vertical-align: top;">
                                        Address
                                    </td>
                                    <td style="padding: 14px 18px; color: #4a2636; font-size: 14px; line-height: 1.5;">
                                        {order.get('buyer_address')}
                                    </td>
                                </tr>

                            </table>

                        </td>
                    </tr>


                    <!-- Payment Details -->
                    <tr>
                        <td style="padding: 25px 40px 10px;">

                            <div style="
                                font-size: 12px;
                                font-weight: 700;
                                letter-spacing: 1.5px;
                                text-transform: uppercase;
                                color: #a86673;
                                margin-bottom: 12px;
                            ">
                                Payment Details
                            </div>

                            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                                   style="
                                       background-color: #ffffff;
                                       border: 1px solid #eee1db;
                                       border-radius: 14px;
                                   ">

                                <tr>
                                    <td style="padding: 14px 18px; color: #806c73; font-size: 13px;">
                                        Payment Status
                                    </td>
                                    <td align="right"
                                        style="padding: 14px 18px; font-size: 13px; font-weight: 700; color: #62805d;">
                                        {order.get('payment_status')}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="padding: 14px 18px; color: #806c73; font-size: 13px;">
                                        Order ID
                                    </td>
                                    <td align="right"
                                        style="padding: 14px 18px; color: #4a2636; font-size: 13px; font-weight: 600;">
                                        {order['id']}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="padding: 14px 18px; color: #806c73; font-size: 13px;">
                                        Selling Date
                                    </td>
                                    <td align="right"
                                        style="padding: 14px 18px; color: #4a2636; font-size: 13px;">
                                        {order.get('selling_time', '')}
                                    </td>
                                </tr>

                            </table>

                        </td>
                    </tr>


                    <!-- Shipping Status -->
                    <tr>
                        <td style="padding: 25px 40px 10px;">

                            <div style="
                                font-size: 12px;
                                font-weight: 700;
                                letter-spacing: 1.5px;
                                text-transform: uppercase;
                                color: #a86673;
                                margin-bottom: 12px;
                            ">
                                Shipping
                            </div>

                            <div style="
                                padding: 18px 20px;
                                background-color: #f8eee9;
                                border-radius: 14px;
                                border-left: 4px solid #c98080;
                                color: #4a2636;
                                font-size: 15px;
                                font-weight: 600;
                            ">
                                🚚 {order.get('shipping_status', 'Pending')}
                            </div>

                        </td>
                    </tr>


                    <!-- Closing Message -->
                    <tr>
                        <td style="
                            padding: 30px 40px 38px;
                            text-align: center;
                        ">

                            <div style="
                                font-size: 14px;
                                line-height: 1.7;
                                color: #6f5a62;
                            ">
                                We'll share your tracking information as soon as
                                your order is shipped.
                            </div>

                            <div style="
                                margin-top: 10px;
                                font-size: 14px;
                                line-height: 1.7;
                                color: #6f5a62;
                            ">
                                Have a question? Simply reply to this email —
                                we're always happy to help.
                            </div>

                            <div style="
                                margin-top: 25px;
                                font-size: 15px;
                                font-weight: 600;
                                color: #4a2636;
                            ">
                                Thank you for choosing
                            </div>

                            <div style="
                                margin-top: 5px;
                                font-size: 18px;
                                font-weight: 700;
                                color: #8e4d62;
                            ">
                                BibiJan Creations ♡
                            </div>

                        </td>
                    </tr>


                    <!-- Footer -->
                    <tr>
                        <td align="center"
                            style="
                                padding: 20px;
                                background-color: #4a2636;
                            ">

                            <div style="
                                font-size: 11px;
                                letter-spacing: 1px;
                                color: #ead8d1;
                            ">
                                BIBIJAN CREATIONS
                            </div>

                            <div style="
                                margin-top: 7px;
                                font-size: 11px;
                                color: #c9aeb5;
                            ">
                                Made with love ♡
                            </div>

                        </td>
                    </tr>

                </table>

            </td>
        </tr>
    </table>

</body>
</html>
"""
    # ✅ Send email to customer
    if order.get("buyer_email"):
        send_email(subject, body, to_email=order["buyer_email"], html=True)

    flash("Full payment received and order marked as Sold.", "ok")
    return redirect(url_for("admin_bookings"))


@app.post('/admin/orders/<int:order_id>/ship')
@admin_required
def mark_shipped(order_id):
    tracking_number = request.form.get('tracking_number')
    if not tracking_number:
        flash("Tracking number is required to mark as shipped!", "error")
        return redirect(url_for('admin_bookings'))

    result = supabase.table('orders').select('status,payment_status').eq('id', order_id).maybe_single().execute()
    order = result.data if result else None
    if not order or order.get('status') != 'Sold' or order.get('payment_status') != 'Full paid':
        flash('Verify full payment before shipping this order.', 'error')
        return redirect(url_for('admin_bookings'))

    # Update DB
    res = supabase.table('orders').update({
        'shipping_status': 'Shipped',
        'tracking_number': tracking_number
    }).eq('id', order_id).execute()

    order = supabase.table("orders").select("*").eq("id", order_id).single().execute().data

    if order and order.get("buyer_email"):
        buyer_email = order["buyer_email"]
        buyer_name = order.get("buyer_name", "Customer")

        subject = "📦 Your order has been shipped!"
        body = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Your Order Has Shipped - BibiJan Creations</title>
</head>

<body style="
    margin: 0;
    padding: 0;
    background-color: #f7f1ec;
    font-family: Arial, Helvetica, sans-serif;
    color: #4a2636;
">

    <table width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background-color: #f7f1ec; padding: 35px 15px;">
        <tr>
            <td align="center">

                <!-- Main Container -->
                <table width="100%" cellpadding="0" cellspacing="0" border="0"
                       style="
                           max-width: 620px;
                           background-color: #fffdf9;
                           border-radius: 20px;
                           overflow: hidden;
                           box-shadow: 0 4px 20px rgba(74, 38, 54, 0.08);
                       ">

                    <!-- Header -->
                    <tr>
                        <td align="center"
                            style="
                                padding: 32px 25px 24px;
                                background-color: #fffaf5;
                                border-bottom: 1px solid #ead8d1;
                            ">

                            <img
                                src="https://bibijancreations.space/static/logo.png"
                                alt="BibiJan Creations"
                                width="180"
                                style="
                                    display: block;
                                    width: 180px;
                                    max-width: 70%;
                                    height: auto;
                                    border: 0;
                                "
                            >

                            <div style="
                                margin-top: 16px;
                                font-size: 13px;
                                letter-spacing: 2px;
                                color: #a86673;
                                text-transform: uppercase;
                            ">
                                Shipping Update
                            </div>

                        </td>
                    </tr>


                    <!-- Main Message -->
                    <tr>
                        <td style="padding: 35px 40px 20px;">

                            <div style="
                                font-size: 27px;
                                line-height: 1.3;
                                font-weight: 600;
                                color: #4a2636;
                                margin-bottom: 12px;
                            ">
                                Your order is on its way! ♡
                            </div>

                            <div style="
                                font-size: 15px;
                                line-height: 1.7;
                                color: #6f5a62;
                            ">
                                Hi {buyer_name}, good news!
                                Your order has been shipped and is now on its way to you.
                            </div>

                        </td>
                    </tr>


                    <!-- Shipping Status -->
                    <tr>
                        <td style="padding: 10px 40px 20px;">

                            <div style="
                                padding: 20px;
                                background-color: #f8eee9;
                                border: 1px solid #ead8d1;
                                border-radius: 16px;
                                text-align: center;
                            ">

                                <div style="
                                    font-size: 28px;
                                    margin-bottom: 8px;
                                ">
                                    🚚
                                </div>

                                <div style="
                                    font-size: 12px;
                                    letter-spacing: 1.5px;
                                    text-transform: uppercase;
                                    color: #a86673;
                                    font-weight: 700;
                                ">
                                    Shipping Status
                                </div>

                                <div style="
                                    margin-top: 7px;
                                    font-size: 20px;
                                    font-weight: 700;
                                    color: #62805d;
                                ">
                                    Shipped
                                </div>

                            </div>

                        </td>
                    </tr>


                    <!-- Item Details -->
                    <tr>
                        <td style="padding: 10px 40px;">

                            <div style="
                                font-size: 12px;
                                font-weight: 700;
                                letter-spacing: 1.5px;
                                text-transform: uppercase;
                                color: #a86673;
                                margin-bottom: 12px;
                            ">
                                Your Order
                            </div>

                            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                                   style="
                                       background-color: #ffffff;
                                       border: 1px solid #eee1db;
                                       border-radius: 14px;
                                   ">

                                <tr>
                                    <td style="
                                        padding: 16px 18px;
                                        color: #806c73;
                                        font-size: 14px;
                                    ">
                                        Item
                                    </td>

                                    <td align="right"
                                        style="
                                            padding: 16px 18px;
                                            color: #4a2636;
                                            font-size: 14px;
                                            font-weight: 600;
                                        ">
                                        {order.get("model")}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="
                                        padding: 14px 18px;
                                        color: #806c73;
                                        font-size: 14px;
                                    ">
                                        Age
                                    </td>

                                    <td align="right"
                                        style="
                                            padding: 14px 18px;
                                            color: #4a2636;
                                            font-size: 14px;
                                        ">
                                        {order.get("purchased_age") or "N/A"}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="
                                        padding: 16px 18px;
                                        color: #4a2636;
                                        font-size: 15px;
                                        font-weight: 700;
                                        border-top: 1px solid #ead8d1;
                                    ">
                                        Price
                                    </td>

                                    <td align="right"
                                        style="
                                            padding: 16px 18px;
                                            color: #8e4d62;
                                            font-size: 18px;
                                            font-weight: 700;
                                            border-top: 1px solid #ead8d1;
                                        ">
                                        Rs {order.get("price")}
                                    </td>
                                </tr>

                            </table>

                        </td>
                    </tr>


                    <!-- Tracking Number -->
                    <tr>
                        <td style="padding: 25px 40px 15px;">

                            <div style="
                                font-size: 12px;
                                font-weight: 700;
                                letter-spacing: 1.5px;
                                text-transform: uppercase;
                                color: #a86673;
                                margin-bottom: 12px;
                            ">
                                Tracking Information
                            </div>

                            <div style="
                                background-color: #4a2636;
                                border-radius: 16px;
                                padding: 22px 20px;
                                text-align: center;
                            ">

                                <div style="
                                    font-size: 12px;
                                    letter-spacing: 1px;
                                    text-transform: uppercase;
                                    color: #dcbfc5;
                                    margin-bottom: 9px;
                                ">
                                    Tracking Number
                                </div>

                                <div style="
                                    font-size: 21px;
                                    font-weight: 700;
                                    letter-spacing: 1px;
                                    color: #fffaf5;
                                    word-break: break-word;
                                ">
                                    {tracking_number}
                                </div>

                            </div>

                        </td>
                    </tr>


                    <!-- Tracking Explanation -->
                    <tr>
                        <td style="
                            padding: 15px 40px 35px;
                            text-align: center;
                        ">

                            <div style="
                                font-size: 14px;
                                line-height: 1.7;
                                color: #6f5a62;
                            ">
                                You can use the tracking number above to
                                follow your shipment's progress.
                            </div>

                            <div style="
                                margin-top: 25px;
                                font-size: 15px;
                                font-weight: 600;
                                color: #4a2636;
                            ">
                                Thank you for shopping with us ♡
                            </div>

                            <div style="
                                margin-top: 6px;
                                font-size: 17px;
                                font-weight: 700;
                                color: #8e4d62;
                            ">
                                BibiJan Creations
                            </div>

                        </td>
                    </tr>


                    <!-- Footer -->
                    <tr>
                        <td align="center"
                            style="
                                padding: 20px;
                                background-color: #4a2636;
                            ">

                            <div style="
                                font-size: 11px;
                                letter-spacing: 1px;
                                color: #ead8d1;
                            ">
                                BIBIJAN CREATIONS
                            </div>

                            <div style="
                                margin-top: 7px;
                                font-size: 11px;
                                color: #c9aeb5;
                            ">
                                Made with love ♡
                            </div>

                        </td>
                    </tr>

                </table>

            </td>
        </tr>
    </table>

</body>
</html>
"""
        # Send to buyer
        send_email(subject, body, to_email=buyer_email, html=True)

    flash(f'Order {order_id} marked as Shipped with tracking number {tracking_number}', 'ok')
    return redirect(url_for('admin_bookings'))



@app.route('/admin/bookings')
@admin_required
def admin_bookings():
    pending = supabase.table('orders').select('*') \
        .eq('status', 'Booked') \
        .eq('payment_status', 'Pending') \
        .eq('admin_id', session['admin_id']) \
        .order('purchase_time', desc=True) \
        .execute().data

    sold = supabase.table('orders').select('*') \
        .eq('status', 'Sold') \
        .eq('admin_id', session['admin_id']) \
        .order('selling_time', desc=True) \
        .execute().data

    pending = parse_datetime_fields(pending, fields=("purchase_time",))
    sold = parse_datetime_fields(sold, fields=("selling_time",))

    return render_template('admin_bookings.html', pending=pending, sold=sold)


@app.get('/admin/sold')
@admin_required
def admin_sold():
    sold = supabase.table('orders').select('*') \
        .eq('status','Sold') \
        .order('selling_time', desc=True) \
        .execute().data or []

    sold = parse_datetime_fields(sold)   # <-- format dates properly

    return render_template('admin_sold.html', sold=sold)


# -------------------------
# MAIN
# -------------------------
if __name__ == '__main__':
    app.run(debug=True)
