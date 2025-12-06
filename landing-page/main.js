// QuantumPulse Landing Page - Main JavaScript

// ========== AUTH TAB SWITCHING ==========
function switchAuthTab(tab) {
    // Update tab buttons
    const tabs = document.querySelectorAll('.auth-tab');
    tabs.forEach(t => {
        if (t.dataset.tab === tab) {
            t.classList.add('active');
        } else {
            t.classList.remove('active');
        }
    });

    // Update forms
    const forms = document.querySelectorAll('.auth-form');
    forms.forEach(form => {
        if (form.id === `${tab}-form`) {
            form.classList.add('active');
        } else {
            form.classList.remove('active');
        }
    });

    // Hide success panel
    const successPanel = document.getElementById('success-panel');
    if (successPanel) {
        successPanel.classList.remove('active');
    }
}

// ========== FORM VALIDATION ==========
function validateEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(String(email).toLowerCase());
}

function validatePassword(password) {
    return password.length >= 8;
}

function showError(fieldId, message) {
    const errorElement = document.getElementById(`${fieldId}-error`);
    if (errorElement) {
        errorElement.textContent = message;
        errorElement.classList.add('show');
    }
}

function clearError(fieldId) {
    const errorElement = document.getElementById(`${fieldId}-error`);
    if (errorElement) {
        errorElement.textContent = '';
        errorElement.classList.remove('show');
    }
}

function clearAllErrors() {
    const errors = document.querySelectorAll('.form-error');
    errors.forEach(error => {
        error.textContent = '';
        error.classList.remove('show');
    });
}

// ========== SIGN IN HANDLER ==========
function handleSignIn(event) {
    event.preventDefault();
    clearAllErrors();

    const email = document.getElementById('signin-email').value;
    const password = document.getElementById('signin-password').value;

    let hasError = false;

    // Validate email
    if (!validateEmail(email)) {
        showError('signin-email', 'Please enter a valid email address');
        hasError = true;
    }

    // Validate password
    if (!password) {
        showError('signin-password', 'Please enter your password');
        hasError = true;
    }

    if (hasError) {
        return false;
    }

    // Simulate successful sign in
    console.log('Sign in successful:', { email });
    
    // Redirect to dashboard
    window.location.href = 'dashboard.html';
    
    return false;
}

// ========== SIGN UP HANDLER ==========
function handleSignUp(event) {
    event.preventDefault();
    clearAllErrors();

    const name = document.getElementById('signup-name').value.trim();
    const email = document.getElementById('signup-email').value.trim();
    const password = document.getElementById('signup-password').value;
    const confirmPassword = document.getElementById('signup-confirm-password').value;
    const role = document.getElementById('signup-role').value;

    let hasError = false;

    // Validate name
    if (name.length < 2) {
        showError('signup-name', 'Please enter your full name (at least 2 characters)');
        hasError = true;
    }

    // Validate email
    if (!validateEmail(email)) {
        showError('signup-email', 'Please enter a valid email address');
        hasError = true;
    }

    // Validate password
    if (!validatePassword(password)) {
        showError('signup-password', 'Password must be at least 8 characters long');
        hasError = true;
    }

    // Validate password confirmation
    if (password !== confirmPassword) {
        showError('signup-confirm', 'Passwords do not match');
        hasError = true;
    }

    if (hasError) {
        return false;
    }

    // Simulate successful sign up
    console.log('Sign up successful:', { name, email, role });

    // Hide the signup form and show success panel
    const signupForm = document.getElementById('signup-form');
    const successPanel = document.getElementById('success-panel');
    
    if (signupForm && successPanel) {
        signupForm.classList.remove('active');
        successPanel.classList.add('active');

        // Hide tabs
        const authTabs = document.querySelector('.auth-tabs');
        if (authTabs) {
            authTabs.style.display = 'none';
        }
    } else {
        // If we're on a different page structure, redirect to trial success page
        window.location.href = 'trial-success.html';
    }

    return false;
}

// ========== GUEST MODE HANDLER ==========
function handleGuestMode() {
    console.log('Guest mode activated');
    window.location.href = 'dashboard.html?guest=true';
}

// ========== SMOOTH SCROLL FOR ANCHOR LINKS ==========
document.addEventListener('DOMContentLoaded', function() {
    // Smooth scroll for anchor links
    const links = document.querySelectorAll('a[href^="#"]');
    links.forEach(link => {
        link.addEventListener('click', function(e) {
            const href = this.getAttribute('href');
            if (href === '#' || href === '#guest') return;
            
            e.preventDefault();
            const target = document.querySelector(href);
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });

    // Check if we should show guest mode on auth page
    const urlParams = new URLSearchParams(window.location.search);
    if (window.location.hash === '#guest' || urlParams.has('guest')) {
        // Automatically show sign in form with focus on guest button
        switchAuthTab('signin');
    }
});

// ========== NAVBAR SCROLL EFFECT ==========
let lastScroll = 0;
window.addEventListener('scroll', function() {
    const navbar = document.querySelector('.navbar');
    const currentScroll = window.pageYOffset;

    if (navbar) {
        if (currentScroll > 100) {
            navbar.style.background = 'rgba(10, 14, 23, 0.98)';
            navbar.style.boxShadow = '0 2px 16px rgba(0, 0, 0, 0.3)';
        } else {
            navbar.style.background = 'rgba(10, 14, 23, 0.95)';
            navbar.style.boxShadow = 'none';
        }
    }

    lastScroll = currentScroll;
});

// ========== FORM INPUT ENHANCEMENTS ==========
document.addEventListener('DOMContentLoaded', function() {
    // Clear error on input focus
    const inputs = document.querySelectorAll('.form-input, .form-select');
    inputs.forEach(input => {
        input.addEventListener('focus', function() {
            const fieldId = this.id;
            clearError(fieldId);
        });
    });

    // Real-time password confirmation validation
    const confirmPasswordInput = document.getElementById('signup-confirm-password');
    if (confirmPasswordInput) {
        confirmPasswordInput.addEventListener('input', function() {
            const password = document.getElementById('signup-password').value;
            const confirmPassword = this.value;
            
            if (confirmPassword && password !== confirmPassword) {
                showError('signup-confirm', 'Passwords do not match');
            } else {
                clearError('signup-confirm');
            }
        });
    }

    // Real-time email validation
    const emailInputs = document.querySelectorAll('input[type="email"]');
    emailInputs.forEach(input => {
        input.addEventListener('blur', function() {
            if (this.value && !validateEmail(this.value)) {
                showError(this.id, 'Please enter a valid email address');
            }
        });
    });

    // Real-time password validation
    const passwordInputs = document.querySelectorAll('input[type="password"]');
    passwordInputs.forEach(input => {
        if (input.id.includes('signup-password') && !input.id.includes('confirm')) {
            input.addEventListener('input', function() {
                if (this.value && !validatePassword(this.value)) {
                    showError(this.id, 'Password must be at least 8 characters');
                } else {
                    clearError(this.id);
                }
            });
        }
    });
});

// ========== ANIMATION ON SCROLL (OPTIONAL) ==========
function animateOnScroll() {
    const elements = document.querySelectorAll('.feature-card, .value-item, .step');
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.opacity = '0';
                entry.target.style.transform = 'translateY(20px)';
                
                setTimeout(() => {
                    entry.target.style.transition = 'all 0.6s ease';
                    entry.target.style.opacity = '1';
                    entry.target.style.transform = 'translateY(0)';
                }, 100);
                
                observer.unobserve(entry.target);
            }
        });
    }, {
        threshold: 0.1
    });

    elements.forEach(el => {
        observer.observe(el);
    });
}

// Run animation on scroll if on landing page
if (document.querySelector('.hero')) {
    document.addEventListener('DOMContentLoaded', animateOnScroll);
}

// ========== CONSOLE WELCOME MESSAGE ==========
console.log('%cΨ∿ QuantumPulse', 'font-size: 24px; font-weight: bold; background: linear-gradient(135deg, #00d4ff 0%, #0080ff 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent;');
console.log('%cAI-Powered Discord Trading Automation', 'font-size: 14px; color: #00d4ff;');
console.log('Trade smarter, not harder. 🚀');
