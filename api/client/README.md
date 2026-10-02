# Client Store Profile

This folder contains client-specific storefront settings and public assets. Update `store.json` for each client; the application reads it at startup and exposes the values to storefront and admin templates.

- `business_name`, `business_type`, `headline`, `description`, and `footer_tagline` control storefront identity and copy.
- `logo` is the public path for the logo. Put the file in `assets/`; the Acme starter profile expects `assets/temp_logo.png`.
- `variant_label` changes the visible option name (for example, `Age` or `Size`). Product option values and prices continue using the existing database fields.
- `currency_symbol`, `currency_code`, and `advance_payment_percent` control displayed prices and the checkout advance calculation.
- `checkout_terms` and `order_confirmation_message` control checkout terms and the post-order confirmation message.
- Website and social URLs are optional. `email_logo_url` must be an absolute public URL to display a logo in email notifications.

Configure deployment secrets as environment variables, not in this folder: `SECRET_KEY`, `ADMIN_EMAIL`, `SMTP_EMAIL`, `SMTP_PASSWORD`, and optionally `STORE_EMAIL`. Bank transfers use `PAYMENT_BANK_NAME`, `PAYMENT_ACCOUNT_NAME`, `PAYMENT_ACCOUNT_NUMBER`, and optional `PAYMENT_IBAN`. Receipt and product image uploads require `CLOUDINARY_URL`.

Complete `questionnaire.md` before setting up a new client. The Acme logo file was not included in the workspace; add it under `assets/` to activate the configured logo path.

## Temporary Store Previews

The `/try-it-out` flow creates a private preview record that expires after two hours. Local development uses process memory when preview credentials are absent, so different browser sessions can try it without writing to the live store database. Vercel requires the dedicated preview Supabase project.

1. Create a separate Supabase project for preview data and run `previews.sql` in its SQL editor. Enable `pg_cron` if Supabase prompts you to enable the extension.
2. Add `PREVIEW_SUPABASE_URL` and `PREVIEW_SUPABASE_SERVICE_ROLE_KEY` to the server environment for that project. Never use the live store's service-role key for preview records.
3. The preview service stores only the business name, type, tagline, and optional image data. The scheduled job deletes expired rows every 15 minutes; clicking **Exit preview** deletes the current record immediately.

Uploaded preview logos are limited to PNG, JPG, or WebP files up to 256 KB. Keep `SECRET_KEY` configured so preview IDs remain protected by Flask's signed session cookie.