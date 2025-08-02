class AccessibilityMenu {
    constructor() {
        this.isOpen = false;
        this.currentSettings = {
            zoom: 1,
            grayscale: false,
            highContrast: false,
            negative: false,
            noColors: false,
            underlinedLinks: false,
            readable: false
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
        toggle.innerHTML = '♿';
        toggle.setAttribute('aria-label', 'Открыть меню доступности');
        toggle.id = 'accessibility-toggle';

        // Create overlay
        const overlay = document.createElement('div');
        overlay.className = 'accessibility-overlay';
        overlay.id = 'accessibility-overlay';

        // Create menu
        const menu = document.createElement('div');
        menu.className = 'accessibility-menu';
        menu.id = 'accessibility-menu';
        menu.innerHTML = `
            <div class="accessibility-header">
                <h3>Barrierefreiheit</h3>
            </div>
            <div class="accessibility-options">
                <div class="accessibility-option" data-action="zoom-in">
                    <div class="accessibility-icon">🔍+</div>
                    <div class="accessibility-text">Vergrößern</div>
                </div>
                <div class="accessibility-option" data-action="zoom-out">
                    <div class="accessibility-icon">🔍-</div>
                    <div class="accessibility-text">Verkleinern</div>
                </div>
                <div class="accessibility-option" data-action="grayscale">
                    <div class="accessibility-icon">▌▌▌</div>
                    <div class="accessibility-text">Graustufen</div>
                </div>
                <div class="accessibility-option" data-action="high-contrast">
                    <div class="accessibility-icon">●</div>
                    <div class="accessibility-text">Hohe Kontraste</div>
                </div>
                <div class="accessibility-option" data-action="negative">
                    <div class="accessibility-icon">👁️</div>
                    <div class="accessibility-text">Negativ</div>
                </div>
                <div class="accessibility-option" data-action="no-colors">
                    <div class="accessibility-icon">💡</div>
                    <div class="accessibility-text">ohne Farben</div>
                </div>
                <div class="accessibility-option" data-action="underlined-links">
                    <div class="accessibility-icon">🔗</div>
                    <div class="accessibility-text">Unterstrichene Links</div>
                </div>
                <div class="accessibility-option" data-action="readable">
                    <div class="accessibility-icon">A</div>
                    <div class="accessibility-text">Lesbarkeit</div>
                </div>
                <div class="accessibility-option" data-action="reset">
                    <div class="accessibility-icon">↻</div>
                    <div class="accessibility-text">Reset</div>
                </div>
            </div>
        `;

        document.body.appendChild(toggle);
        document.body.appendChild(overlay);
        document.body.appendChild(menu);
    }

    bindEvents() {
        // Toggle button
        document.getElementById('accessibility-toggle').addEventListener('click', () => {
            this.toggleMenu();
        });

        // Overlay click
        document.getElementById('accessibility-overlay').addEventListener('click', () => {
            this.closeMenu();
        });

        // Menu options
        document.querySelectorAll('.accessibility-option').forEach(option => {
            option.addEventListener('click', (e) => {
                const action = e.currentTarget.dataset.action;
                this.handleAction(action);
            });
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
        const overlay = document.getElementById('accessibility-overlay');

        if (this.isOpen) {
            menu.classList.add('open');
            overlay.classList.add('active');
        } else {
            menu.classList.remove('open');
            overlay.classList.remove('active');
        }
    }

    closeMenu() {
        this.isOpen = false;
        document.getElementById('accessibility-menu').classList.remove('open');
        document.getElementById('accessibility-overlay').classList.remove('active');
    }

    handleAction(action) {
        switch(action) {
            case 'zoom-in':
                this.zoomIn();
                break;
            case 'zoom-out':
                this.zoomOut();
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
            case 'underlined-links':
                this.toggleUnderlinedLinks();
                break;
            case 'readable':
                this.toggleReadable();
                break;
            case 'reset':
                this.reset();
                break;
        }
        this.saveSettings();
    }

    zoomIn() {
        this.currentSettings.zoom = Math.min(this.currentSettings.zoom + 0.2, 2);
        this.applyZoom();
    }

    zoomOut() {
        this.currentSettings.zoom = Math.max(this.currentSettings.zoom - 0.2, 0.5);
        this.applyZoom();
    }

    applyZoom() {
        document.body.style.transform = `scale(${this.currentSettings.zoom})`;
        document.body.style.transformOrigin = 'top left';
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

    toggleUnderlinedLinks() {
        this.currentSettings.underlinedLinks = !this.currentSettings.underlinedLinks;
        document.body.classList.toggle('underlined-links', this.currentSettings.underlinedLinks);
    }

    toggleReadable() {
        this.currentSettings.readable = !this.currentSettings.readable;
        document.body.classList.toggle('readable', this.currentSettings.readable);
    }

    reset() {
        this.currentSettings = {
            zoom: 1,
            grayscale: false,
            highContrast: false,
            negative: false,
            noColors: false,
            underlinedLinks: false,
            readable: false
        };

        document.body.style.transform = '';
        document.body.style.transformOrigin = '';
        document.body.className = document.body.className.replace(/grayscale|high-contrast|negative|no-colors|underlined-links|readable/g, '');
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
        if (this.currentSettings.zoom !== 1) {
            this.applyZoom();
        }
        if (this.currentSettings.grayscale) document.body.classList.add('grayscale');
        if (this.currentSettings.highContrast) document.body.classList.add('high-contrast');
        if (this.currentSettings.negative) document.body.classList.add('negative');
        if (this.currentSettings.noColors) document.body.classList.add('no-colors');
        if (this.currentSettings.underlinedLinks) document.body.classList.add('underlined-links');
        if (this.currentSettings.readable) document.body.classList.add('readable');
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new AccessibilityMenu();
});
