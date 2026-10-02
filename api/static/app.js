// Modern App.js with Enhanced Interactions and Animations

// Countdown timer functionality
function updateCountdowns() {
  const countdownElements = document.querySelectorAll('.countdown');
  
  countdownElements.forEach(el => {
    const deadline = el.getAttribute('data-deadline');
    if (!deadline) return;
    
    const deadlineTime = new Date(deadline).getTime();
    const now = new Date().getTime();
    const timeLeft = deadlineTime - now;
    
    if (timeLeft > 0) {
      const minutes = Math.floor((timeLeft % (1000 * 60 * 60)) / (1000 * 60));
      const seconds = Math.floor((timeLeft % (1000 * 60)) / 1000);
      el.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
      
      // Add urgency styling when less than 2 minutes
      if (timeLeft < 120000) { // 2 minutes
        el.style.animation = 'countdownUrgent 0.5s ease-in-out infinite';
        el.style.color = '#ef4444';
      }
    } else {
      el.textContent = 'Expired';
      el.style.color = '#ef4444';
      el.style.animation = 'none';
      
      // Optionally refresh the page when expired
      setTimeout(() => {
        window.location.reload();
      }, 2000);
    }
  });
}

// Add urgency animation keyframes
const urgentStyle = document.createElement('style');
urgentStyle.textContent = `
  @keyframes countdownUrgent {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.1); filter: brightness(1.2); }
  }
`;
document.head.appendChild(urgentStyle);

// Initialize countdown timers
if (document.querySelectorAll('.countdown').length > 0) {
  updateCountdowns();
  setInterval(updateCountdowns, 1000);
}

// Modern page transitions and animations
document.addEventListener('DOMContentLoaded', function() {
  
  // Add staggered animation to cards
  const cards = document.querySelectorAll('.card');
  cards.forEach((card, index) => {
    card.style.animationDelay = `${index * 0.1}s`;
  });
  
  // Add staggered animation to list items
  const listItems = document.querySelectorAll('.list li');
  listItems.forEach((item, index) => {
    item.style.animationDelay = `${index * 0.1}s`;
  });
  
  // Add staggered animation to table rows
  const tableRows = document.querySelectorAll('.table tbody tr');
  tableRows.forEach((row, index) => {
    row.style.animationDelay = `${index * 0.05}s`;
  });
  
  // Enhanced button interactions
  const buttons = document.querySelectorAll('.btn');
  buttons.forEach(btn => {
    // Add ripple effect on click
    btn.addEventListener('click', function(e) {
      const ripple = document.createElement('span');
      const rect = this.getBoundingClientRect();
      const size = Math.max(rect.width, rect.height);
      const x = e.clientX - rect.left - size / 2;
      const y = e.clientY - rect.top - size / 2;
      
      ripple.style.cssText = `
        position: absolute;
        width: ${size}px;
        height: ${size}px;
        left: ${x}px;
        top: ${y}px;
        background: rgba(255, 255, 255, 0.3);
        border-radius: 50%;
        transform: scale(0);
        animation: ripple 0.6s ease-out;
        pointer-events: none;
      `;
      
      // Add ripple animation
      const rippleStyle = document.createElement('style');
      rippleStyle.textContent = `
        @keyframes ripple {
          to {
            transform: scale(2);
            opacity: 0;
          }
        }
      `;
      document.head.appendChild(rippleStyle);
      
      this.appendChild(ripple);
      setTimeout(() => ripple.remove(), 600);
    });
    
    // Add loading state for form submissions (disabled for login forms)
    if (btn.type === 'submit' && !btn.closest('form').action.includes('/login')) {
      const form = btn.closest('form');
      if (form) {
        form.addEventListener('submit', function(e) {
          // Show loading state only for non-login forms
          const originalText = btn.innerHTML;
          
          setTimeout(() => {
            btn.innerHTML = `
              <span style="display: inline-flex; align-items: center; gap: 8px;">
                <span class="loading-spinner"></span>
                Processing...
              </span>
            `;
            btn.disabled = true;
            
            // Add spinner styles
            if (!document.getElementById('spinner-styles')) {
              const spinnerStyle = document.createElement('style');
              spinnerStyle.id = 'spinner-styles';
              spinnerStyle.textContent = `
                .loading-spinner {
                  width: 16px;
                  height: 16px;
                  border: 2px solid rgba(255, 255, 255, 0.3);
                  border-top: 2px solid white;
                  border-radius: 50%;
                  animation: spin 1s linear infinite;
                }
                @keyframes spin {
                  0% { transform: rotate(0deg); }
                  100% { transform: rotate(360deg); }
                }
              `;
              document.head.appendChild(spinnerStyle);
            }
          }, 10);
        });
      }
    }
  });
  
  // Enhanced form interactions
  const inputs = document.querySelectorAll('.input, textarea, select');
  inputs.forEach(input => {
    // Add floating label effect
    input.addEventListener('focus', function() {
      this.parentElement.classList.add('focused');
    });
    
    input.addEventListener('blur', function() {
      this.parentElement.classList.remove('focused');
      if (this.value) {
        this.parentElement.classList.add('filled');
      } else {
        this.parentElement.classList.remove('filled');
      }
    });
    
    // Add input validation styling
    input.addEventListener('invalid', function() {
      this.style.borderColor = '#ef4444';
      this.style.boxShadow = '0 0 0 3px rgba(239, 68, 68, 0.3)';
    });
    
    input.addEventListener('input', function() {
      if (this.checkValidity()) {
        this.style.borderColor = 'rgba(255, 255, 255, 0.2)';
        this.style.boxShadow = 'none';
      }
    });
  });
  
  // Enhanced media interactions
  const mediaElements = document.querySelectorAll('.media-strip img, .media-strip video');
  mediaElements.forEach((media, index) => {
    media.style.animationDelay = `${index * 0.1}s`;
    
    // Add click to expand functionality
    media.addEventListener('click', function() {
      showMediaModal(this.src, this.tagName.toLowerCase());
    });
    
    // Add lazy loading effect
    if (media.tagName.toLowerCase() === 'img') {
      media.style.transition = 'filter 0.3s ease';
      
      media.addEventListener('load', function() {
        this.style.filter = 'none';
      });
    }
  });
  
  // Auto-hide flash messages
  const flashMessages = document.querySelectorAll('.grid .card[role="alert"]');
  flashMessages.forEach(msg => {
    setTimeout(() => {
      if (msg.parentElement) {
        msg.style.animation = 'slideOutUp 0.5s ease-out forwards';
        setTimeout(() => msg.remove(), 500);
      }
    }, 4000);
  });
  
  // Add smooth scrolling to anchor links
  const anchorLinks = document.querySelectorAll('a[href^="#"]');
  anchorLinks.forEach(link => {
    link.addEventListener('click', function(e) {
      e.preventDefault();
      const target = document.querySelector(this.getAttribute('href'));
      if (target) {
        target.scrollIntoView({
          behavior: 'smooth',
          block: 'start'
        });
      }
    });
  });
  
  // Add intersection observer for scroll animations
  const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
  };
  
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.style.animation = 'fadeInUp 0.6s ease-out forwards';
      }
    });
  }, observerOptions);
  
  // Observe elements for scroll animations
  const animatedElements = document.querySelectorAll('.card, .table, .list');
  animatedElements.forEach(el => {
    observer.observe(el);
  });
});

// Media modal functionality
function showMediaModal(src, type) {
  // Create modal overlay
  const modal = document.createElement('div');
  modal.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.9);
    display: flex;
    justify-content: center;
    align-items: center;
    z-index: 1000;
    backdrop-filter: blur(10px);
    animation: fadeIn 0.3s ease-out;
  `;
  
  // Create media element
  const mediaEl = document.createElement(type);
  mediaEl.src = src;
  mediaEl.style.cssText = `
    max-width: 90%;
    max-height: 90%;
    border-radius: 12px;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
    animation: scaleIn 0.3s ease-out;
  `;
  
  if (type === 'video') {
    mediaEl.controls = true;
    mediaEl.autoplay = true;
  }
  
  // Add scale animation
  const scaleStyle = document.createElement('style');
  scaleStyle.textContent = `
    @keyframes scaleIn {
      from { transform: scale(0.8); opacity: 0; }
      to { transform: scale(1); opacity: 1; }
    }
  `;
  document.head.appendChild(scaleStyle);
  
  // Close on click outside
  modal.addEventListener('click', function(e) {
    if (e.target === modal) {
      modal.style.animation = 'fadeOut 0.3s ease-out forwards';
      setTimeout(() => modal.remove(), 300);
    }
  });
  
  // Close on escape key
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && document.body.contains(modal)) {
      modal.style.animation = 'fadeOut 0.3s ease-out forwards';
      setTimeout(() => modal.remove(), 300);
    }
  });
  
  modal.appendChild(mediaEl);
  document.body.appendChild(modal);
  
  // Add fadeOut animation
  const fadeOutStyle = document.createElement('style');
  fadeOutStyle.textContent = `
    @keyframes fadeOut {
      from { opacity: 1; }
      to { opacity: 0; }
    }
  `;
  document.head.appendChild(fadeOutStyle);
}

// Enhanced table interactions
function enhanceTableInteractions() {
  const tables = document.querySelectorAll('.table');
  tables.forEach(table => {
    // Add sorting functionality (if needed)
    const headers = table.querySelectorAll('th');
    headers.forEach((header, index) => {
      header.style.cursor = 'pointer';
      header.addEventListener('click', function() {
        // Add sorting logic here if needed
        this.style.background = 'rgba(255, 255, 255, 0.2)';
        setTimeout(() => {
          this.style.background = 'rgba(255, 255, 255, 0.1)';
        }, 200);
      });
    });
    
    // Add row hover effects with delay
    const rows = table.querySelectorAll('tbody tr');
    rows.forEach(row => {
      row.addEventListener('mouseenter', function() {
        this.style.transform = 'scale(1.02)';
        this.style.zIndex = '10';
      });
      
      row.addEventListener('mouseleave', function() {
        this.style.transform = 'scale(1)';
        this.style.zIndex = 'auto';
      });
    });
  });
}

// Add parallax scrolling effect to background
function addParallaxEffect() {
  let scrolled = 0;
  
  window.addEventListener('scroll', function() {
    scrolled = window.pageYOffset;
    const parallax = document.body;
    const speed = scrolled * 0.5;
    
    parallax.style.backgroundPosition = `center ${speed}px`;
  });
}

// Add typing animation for headings
function addTypingAnimation() {
  const headings = document.querySelectorAll('h1, h2');
  
  headings.forEach(heading => {
    const text = heading.textContent;
    heading.textContent = '';
    heading.style.borderRight = '2px solid rgba(255, 255, 255, 0.7)';
    heading.style.animation = 'blink 1s infinite';
    
    let i = 0;
    const typeWriter = setInterval(() => {
      if (i < text.length) {
        heading.textContent += text.charAt(i);
        i++;
      } else {
        clearInterval(typeWriter);
        setTimeout(() => {
          heading.style.borderRight = 'none';
          heading.style.animation = 'none';
        }, 1000);
      }
    }, 100);
  });
  
  // Add blinking cursor animation
  const blinkStyle = document.createElement('style');
  blinkStyle.textContent = `
    @keyframes blink {
      0%, 50% { border-color: rgba(255, 255, 255, 0.7); }
      51%, 100% { border-color: transparent; }
    }
  `;
  document.head.appendChild(blinkStyle);
}

// Add particle background effect
function addParticleEffect() {
  const canvas = document.createElement('canvas');
  canvas.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    z-index: -1;
    pointer-events: none;
  `;
  
  document.body.appendChild(canvas);
  
  const ctx = canvas.getContext('2d');
  let particles = [];
  
  function resizeCanvas() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  }
  
  window.addEventListener('resize', resizeCanvas);
  resizeCanvas();
  
  // Create particles
  for (let i = 0; i < 50; i++) {
    particles.push({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      size: Math.random() * 3 + 1,
      speedX: Math.random() * 2 - 1,
      speedY: Math.random() * 2 - 1,
      opacity: Math.random() * 0.5 + 0.2
    });
  }
  
  function animateParticles() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    particles.forEach(particle => {
      particle.x += particle.speedX;
      particle.y += particle.speedY;
      
      // Wrap around edges
      if (particle.x > canvas.width) particle.x = 0;
      if (particle.x < 0) particle.x = canvas.width;
      if (particle.y > canvas.height) particle.y = 0;
      if (particle.y < 0) particle.y = canvas.height;
      
      // Draw particle
      ctx.beginPath();
      ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255, 255, 255, ${particle.opacity})`;
      ctx.fill();
    });
    
    requestAnimationFrame(animateParticles);
  }
  
  animateParticles();
}

// Enhanced initialization
document.addEventListener('DOMContentLoaded', function() {
  enhanceTableInteractions();
  addParallaxEffect();
  addParticleEffect();
  
  // Add typing animation after a delay
  setTimeout(addTypingAnimation, 500);
  
  // Add loading completion animation
  document.body.style.opacity = '0';
  document.body.style.transition = 'opacity 0.5s ease-in';
  
  window.addEventListener('load', function() {
    document.body.style.opacity = '1';
  });
});

// Add swipe gestures for mobile
let touchStartX = 0;
let touchEndX = 0;

document.addEventListener('touchstart', function(e) {
  touchStartX = e.changedTouches[0].screenX;
});

document.addEventListener('touchend', function(e) {
  touchEndX = e.changedTouches[0].screenX;
  handleSwipe();
});

function handleSwipe() {
  const swipeThreshold = 50;
  const diff = touchStartX - touchEndX;
  
  if (Math.abs(diff) > swipeThreshold) {
    if (diff > 0) {
      // Swiped left - could trigger navigation
      console.log('Swiped left');
    } else {
      // Swiped right - could trigger navigation
      console.log('Swiped right');
    }
  }
}

// Add Easter egg - Konami code (removed rainbow effect)
let konamiCode = [];
const konamiSequence = [
  'ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown',
  'ArrowLeft', 'ArrowRight', 'ArrowLeft', 'ArrowRight',
  'KeyB', 'KeyA'
];

document.addEventListener('keydown', function(e) {
  konamiCode.push(e.code);
  
  if (konamiCode.length > konamiSequence.length) {
    konamiCode.shift();
  }
  
  if (konamiCode.join(',') === konamiSequence.join(',')) {
    // Easter egg activated! - Subtle blue pulse effect
    document.body.style.animation = 'bluePulse 2s ease-in-out 3 times';
    
    const pulseStyle = document.createElement('style');
    pulseStyle.textContent = `
      @keyframes bluePulse {
        0%, 100% { filter: brightness(1); }
        50% { filter: brightness(1.2) saturate(1.3); }
      }
    `;
    document.head.appendChild(pulseStyle);
    
    setTimeout(() => {
      document.body.style.animation = 'none';
    }, 6000);
    
    konamiCode = []; // Reset
  }
});

// Performance optimization - Debounce scroll events
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

// Apply debouncing to scroll-heavy functions
window.addEventListener('scroll', debounce(function() {
  // Any scroll-heavy operations go here
}, 16)); // ~60fps

console.log('🎨 Modern UI loaded with animations and interactions!');