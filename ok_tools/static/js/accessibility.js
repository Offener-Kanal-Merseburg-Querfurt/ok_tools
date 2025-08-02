class AccessibilityMenu {
    constructor() {
        this.isOpen = false;
        this.currentSettings = {
            largeText: false,
            smallText: false,
            grayscale: false,
            highContrast: false,
            negative: false,
            noColors: false,
            underlineLinks: false,
            readableFont: false
        };
        this.init();
    }

    init() {
        this.createMenu();
        this.bindEvents();
        this.loadSettings();
    }

    createMenu() {
        // Create toggle button
        const toggle = document.createElement('button');
        toggle.className = 'accessibility-toggle';
        toggle.innerHTML = `
            <svg viewBox="0 0 24 24">
                <path d="M12 2C13.1 2 14 2.9 14 4C14 5.1 13.1 6 12 6C10.9 6 10 5.1 10 4C10 2.9 10.9 2 12 2ZM21 9V7L15 7.5V9H21ZM3 9V7L9 7.5V9H3ZM8 10V22H10V10H8ZM14 10V22H16V10H14Z"/>

            </svg>
        `;
        toggle.setAttribute('aria-label', 'Barrierefreiheit');
        toggle.id = 'accessibility-toggle';

        // Create menu
        const menu = document.createElement('div');
        menu.className = 'accessibility-menu';
        menu.id = 'accessibility-menu';
        menu.innerHTML = `
            <div class="menu-header">
                Barrierefreiheit
                <div class="wheelchair-icon">
                    <svg viewBox="0 0 24 24">
                       <path d="M12 2C13.1 2 14 2.9 14 4C14 5.1 13.1 6 12 6C10.9 6 10 5.1 10 4C10 2.9 10.9 2 12 2ZM21 9V7L15 7.5V9H21ZM3 9V7L9 7.5V9H3ZM8 10V22H10V10H8ZM14 10V22H16V10H14Z"/>
                    </svg>
                </div>
            </div>
            <div class="menu-content">
                <div class="menu-item" data-action="large-text">
                    <svg viewBox="0 0 24 24">
                        <path d="M19 13H13V19H11V13H5V11H11V5H13V11H19V13Z"/>
                    </svg>
                    <span>Vergrößern</span>
                </div>
                <div class="menu-item" data-action="small-text">
                    <svg viewBox="0 0 24 24">
                        <path d="M9 11H15L12 8L9 11ZM12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM16 13H8V11H16V13Z"/>
                </svg>
                    </svg>
                    <span>Verkleinern</span>
                </div>
                <div class="menu-item" data-action="grayscale">
                    <svg viewBox="0 0 24 24">
                        <path d="M3 3L21 21L19.59 22.41L1.18 4L2.59 2.59L3 3ZM12 2C6.48 2 2 6.48 2 12C2 14.09 2.66 16.01 3.74 17.58L6.17 15.15C6.06 14.78 6 14.4 6 14C6 10.69 8.69 8 12 8C12.4 8 12.78 8.06 13.15 8.17L15.58 5.74C14.01 4.66 12.09 4 12 4V2ZM18.26 6.42L15.83 8.85C15.94 9.22 16 9.6 16 10C16 13.31 13.31 16 10 16C9.6 16 9.22 15.94 8.85 15.83L6.42 18.26C7.99 19.34 9.91 20 12 20C17.52 20 22 15.52 22 10C22 7.91 21.34 5.99 20.26 4.42L18.26 6.42Z"/>
                    </svg>
                    <span>Graustufen</span>
                </div>
                <div class="menu-item" data-action="high-contrast">
                    <svg viewBox="0 0 24 24">
                        <path d="M12 2C6.48 2 2 6.48 2 12S6.48 22 12 22 22 17.52 22 12 17.52 2 12 2ZM12 20V4C16.41 4 20 7.59 20 12S16.41 20 12 20Z"/>
                    </svg>
                    <span>Hohe Kontraste</span>
                </div>
                <div class="menu-item" data-action="negative">
                    <svg viewBox="0 0 24 24">
                        <path d="M12 2C6.48 2 2 6.48 2 12S6.48 22 12 22 22 17.52 22 12 17.52 2 12 2ZM4 12C4 16.41 7.59 20 12 20V4C7.59 4 4 7.59 4 12Z"/>
                    </svg>
                    <span>Negativ</span>
                </div>
                <div class="menu-item" data-action="no-colors">
                    <svg viewBox="0 0 24 24">
                        <path d="M12 4.5C7 4.5 2.73 7.61 1 12C2.73 16.39 7 19.5 12 19.5S21.27 16.39 23 12C21.27 7.61 17 4.5 12 4.5ZM12 17C9.24 17 7 14.76 7 12S9.24 7 12 7 17 9.24 17 12 14.76 17 12 17ZM12 9C10.34 9 9 10.34 9 12S10.34 15 12 15 15 13.66 15 12 13.66 9 12 9Z"/>
                    </svg>
                    <span>ohne Farben</span>
                </div>
                <div class="menu-item" data-action="underline-links">
                    <svg viewBox="0 0 24 24">
                        <path d="M10.24 17.73L8.82 19.15L2 12.33L8.82 5.51L10.24 6.93L4.91 12.33L10.24 17.73ZM14.27 6.93L15.69 5.51L22.51 12.33L15.69 19.15L14.27 17.73L19.6 12.33L14.27 6.93Z"/>
                    </svg>
                    <span>Unterstrichene Links</span>
                </div>
                <div class="menu-item" data-action="readable-font">
                    <svg viewBox="0 0 24 24">
                        <path d="M5 4V7H10.5V19H13.5V7H19V4H5Z"/>
                    </svg>
                    <span>Lesbarkeit</span>
                </div>
                <div class="menu-item reset-item" data-action="reset">
                    <svg viewBox="0 0 24 24">
                        <path d="M17.65 6.35C16.2 4.9 14.21 4 12 4C7.58 4 4 7.58 4 12S7.58 20 12 20C15.73 20 18.84 17.45 19.73 14H17.65C16.83 16.33 14.61 18 12 18C8.69 18 6 15.31 6 12S8.69 6 12 6C13.66 6 15.14 6.69 16.22 7.78L13 11H20V4L17.65 6.35Z"/>
                    </svg>
                    <span>Reset</span>
                </div>
            </div>
        `;

        document.body.appendChild(toggle);
        document.body.appendChild(menu);
    }

    bindEvents() {
        // Toggle button
        document.getElementById('accessibility-toggle').addEventListener('click', () => {
            this.toggleMenu();
        });

        // Menu options
        document.querySelectorAll('.menu-item').forEach(option => {
            option.addEventListener('click', (e) => {
                const action = e.currentTarget.dataset.action;
                this.handleAction(action);
            });
        });

        // Close menu when clicking outside
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.accessibility-toggle') && !e.target.closest('.accessibility-menu')) {
                this.closeMenu();
            }
        });

        // Keyboard navigation
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen) {
                this.closeMenu();
            }
        });
    }

    toggleMenu() {
        this.isOpen = !this.isOpen;
        const menu = document.getElementById('accessibility-menu');

        if (this.isOpen) {
            menu.classList.add('active');
        } else {
            menu.classList.remove('active');
        }
    }

    closeMenu() {
        this.isOpen = false;
        document.getElementById('accessibility-menu').classList.remove('active');
    }

    handleAction(action) {
        // Remove active class from all menu items
        document.querySelectorAll('.menu-item').forEach(item => {
            item.classList.remove('active');
        });

        // Add active class to clicked item
        const clickedItem = document.querySelector(`[data-action="${action}"]`);
        if (clickedItem) {
            clickedItem.classList.add('active');
        }

        switch(action) {
            case 'large-text':
                this.toggleLargeText();
                break;
            case 'small-text':
                this.toggleSmallText();
                break;
            case 'grayscale':
                this.toggleGrayscale();
                break;
            case 'high-contrast':
                this.toggleHighContrast();
                break;
            case 'negative':
                this.toggleNegative();
                break;
            case 'no-colors':
                this.toggleNoColors();
                break;
            case 'underline-links':
                this.toggleUnderlineLinks();
                break;
            case 'readable-font':
                this.toggleReadableFont();
                break;
            case 'reset':
                this.reset();
                break;
        }
        this.saveSettings();
    }

    toggleLargeText() {
        this.currentSettings.largeText = !this.currentSettings.largeText;
        this.currentSettings.smallText = false;
        document.body.classList.toggle('large-text', this.currentSettings.largeText);
        document.body.classList.remove('small-text');
    }

    toggleSmallText() {
        this.currentSettings.smallText = !this.currentSettings.smallText;
        this.currentSettings.largeText = false;
        document.body.classList.toggle('small-text', this.currentSettings.smallText);
        document.body.classList.remove('large-text');
    }

    toggleGrayscale() {
        this.currentSettings.grayscale = !this.currentSettings.grayscale;
        document.body.classList.toggle('grayscale', this.currentSettings.grayscale);
    }

    toggleHighContrast() {
        this.currentSettings.highContrast = !this.currentSettings.highContrast;
        document.body.classList.toggle('high-contrast', this.currentSettings.highContrast);
    }

    toggleNegative() {
        this.currentSettings.negative = !this.currentSettings.negative;
        document.body.classList.toggle('negative', this.currentSettings.negative);
    }

    toggleNoColors() {
        this.currentSettings.noColors = !this.currentSettings.noColors;
        document.body.classList.toggle('no-colors', this.currentSettings.noColors);
    }

    toggleUnderlineLinks() {
        this.currentSettings.underlineLinks = !this.currentSettings.underlineLinks;
        document.body.classList.toggle('underline-links', this.currentSettings.underlineLinks);
    }

    toggleReadableFont() {
        this.currentSettings.readableFont = !this.currentSettings.readableFont;
        document.body.classList.toggle('readable-font', this.currentSettings.readableFont);
    }

    reset() {
        this.currentSettings = {
            largeText: false,
            smallText: false,
            grayscale: false,
            highContrast: false,
            negative: false,
            noColors: false,
            underlineLinks: false,
            readableFont: false
        };

        document.body.className = document.body.className.replace(/large-text|small-text|grayscale|high-contrast|negative|no-colors|underline-links|readable-font/g, '');

        // Remove active class from all menu items
        document.querySelectorAll('.menu-item').forEach(item => {
            item.classList.remove('active');
        });
    }

    saveSettings() {
        localStorage.setItem('accessibility-settings', JSON.stringify(this.currentSettings));
    }

    loadSettings() {
        const saved = localStorage.getItem('accessibility-settings');
        if (saved) {
            this.currentSettings = JSON.parse(saved);
            this.applySettings();
        }
    }

    applySettings() {
        if (this.currentSettings.largeText) document.body.classList.add('large-text');
        if (this.currentSettings.smallText) document.body.classList.add('small-text');
        if (this.currentSettings.grayscale) document.body.classList.add('grayscale');
        if (this.currentSettings.highContrast) document.body.classList.add('high-contrast');
        if (this.currentSettings.negative) document.body.classList.add('negative');
        if (this.currentSettings.noColors) document.body.classList.add('no-colors');
        if (this.currentSettings.underlineLinks) document.body.classList.add('underline-links');
        if (this.currentSettings.readableFont) document.body.classList.add('readable-font');
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new AccessibilityMenu();
});
