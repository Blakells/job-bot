"""Browser session management, screenshots, and overlay dismissal."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from job_bot.config import ATS_PLATFORMS, COOKIE_DIR

logger = logging.getLogger(__name__)


def detect_ats_platform(url: str) -> str:
    """Detect which ATS platform a URL belongs to."""
    url_lower = url.lower()
    for pattern, platform in ATS_PLATFORMS.items():
        if pattern in url_lower:
            return platform
    return "unknown"


def get_session_path(platform: str) -> Path:
    """Get the path to saved browser session for an ATS platform."""
    COOKIE_DIR.mkdir(parents=True, exist_ok=True)
    return COOKIE_DIR / f"{platform}_session.json"


def has_saved_session(platform: str) -> bool:
    """Check if we have a saved browser session for this ATS."""
    return get_session_path(platform).exists()


def save_browser_session(context, platform: str) -> None:
    """Save browser cookies/session state for reuse."""
    path = get_session_path(platform)
    COOKIE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        context.storage_state(path=str(path))
        print(f"  >> Session saved for {platform}")
    except Exception as e:
        logger.warning("Could not save session for %s: %s", platform, e)


def screenshot(page, name, output_dir="outputs/screenshots"):
    """Take and save a screenshot, clearing any overlays first."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = f"{output_dir}/{name}.png"

    # Clear cookie banners, modals, and backdrops before the screenshot
    try:
        page.evaluate("""() => {
            document.querySelectorAll(
                '[class*="cookie"], [class*="Cookie"], [id*="cookie"], [id*="Cookie"], ' +
                '[class*="consent"], [class*="Consent"], [class*="gdpr"], ' +
                '[data-role="modal-wrapper"], [data-role="backdrop"], ' +
                '[data-evergreen-dialog-backdrop], .modal-backdrop, ' +
                '[class*="modal-overlay"], [class*="dialog-backdrop"]'
            ).forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width > 200 || el.getAttribute('data-role')) {
                    el.remove();
                }
            });
            document.body.style.overflow = '';
            document.documentElement.style.overflow = '';
        }""")
        time.sleep(0.3)
    except Exception:
        pass

    page.screenshot(path=path)
    print(f"  >> Screenshot: {path}")
    return path


def dismiss_cookie_banner(page):
    """
    Automatically dismiss cookie consent banners that block page interaction.
    Uses JavaScript for reliability.
    """
    try:
        removed = page.evaluate("""() => {
            let dismissed = false;

            // Strategy 1: Click "Accept all" / "Accept" / "OK" buttons
            const buttonTexts = [
                'accept all', 'accept all cookies', 'accept cookies', 'accept',
                'allow all', 'allow all cookies', 'allow cookies', 'allow',
                'i accept', 'i agree', 'agree', 'ok', 'got it', 'dismiss',
                'agree and close', 'consent', 'save settings'
            ];

            const allButtons = document.querySelectorAll('button, a[role="button"], [class*="btn"]');
            for (const btn of allButtons) {
                const text = (btn.textContent || btn.innerText || '').trim().toLowerCase();
                if (buttonTexts.some(t => text === t || text.startsWith(t))) {
                    const rect = btn.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        btn.click();
                        dismissed = true;
                        break;
                    }
                }
            }

            // Strategy 2: Click known cookie consent selectors
            if (!dismissed) {
                const selectors = [
                    '#onetrust-accept-btn-handler',
                    '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
                    '.evidon-banner-acceptbutton',
                    '[data-testid="cookie-accept"]',
                    'button[id*="accept"]',
                    'button[class*="accept"]',
                    '.cc-accept', '.cc-btn',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) { el.click(); dismissed = true; break; }
                }
            }

            // Strategy 3: Remove cookie banners from DOM
            const removeSelectors = [
                '[class*="cookie-banner"]', '[class*="cookie-consent"]',
                '[class*="cookieBanner"]', '[class*="CookieConsent"]',
                '[id*="cookie-banner"]', '[id*="cookie-consent"]',
                '[id*="cookieBanner"]', '[id*="CookieConsent"]',
                '[data-testid*="cookie"]', '[class*="gdpr"]',
                '.cc-window', '#onetrust-banner-sdk', '#onetrust-policy',
                '#onetrust-consent-sdk',
                '#CybotCookiebotDialog',
            ];
            for (const sel of removeSelectors) {
                document.querySelectorAll(sel).forEach(el => {
                    el.remove();
                    dismissed = true;
                });
            }

            document.body.style.overflow = '';
            document.documentElement.style.overflow = '';
            return dismissed;
        }""")
        if removed:
            print("  >> Dismissed cookie banner")
            time.sleep(0.5)
        return removed
    except Exception:
        return False


def _has_form_inputs(page, container_selector: str) -> bool:
    """Check if a container element has form inputs inside it.

    Modals that contain file inputs, text fields, selects, etc. are likely
    part of the application form (e.g. resume upload dialog) and must NOT
    be dismissed.
    """
    try:
        return page.evaluate("""(sel) => {
            const el = document.querySelector(sel);
            if (!el) return false;
            return el.querySelector(
                'input[type="file"], input[type="text"], input[type="email"], '
                + 'input[type="tel"], input[type="number"], textarea, '
                + 'select, [role="combobox"]'
            ) !== null;
        }""", container_selector)
    except Exception:
        return True  # err on the side of caution


def dismiss_overlays(page):
    """
    Dismiss modal overlays, dialogs, backdrops, and advertisements
    that block interaction with the form underneath.

    IMPORTANT: Never dismiss modals that contain form inputs — they may
    BE the application form (e.g. Paylocity's resume upload dialog).
    """
    dismissed = False

    # Strategy 1: Remove known ad/consent modals by ID (e.g. Paylocity citrus modal)
    # BUT skip any that contain form inputs — Paylocity reuses the citrus-modal
    # wrapper for the resume upload dialog.
    try:
        removed_count = page.evaluate("""() => {
            let removed = 0;
            document.querySelectorAll('[id*="citrus-modal"]').forEach(el => {
                // Skip modals that contain form inputs (resume upload, etc.)
                if (el.querySelector('input, textarea, select, [role="combobox"]')) {
                    return;
                }
                el.remove();
                removed++;
            });
            if (removed > 0) {
                document.body.classList.remove('modal-open');
                document.body.style.overflow = '';
            }
            return removed;
        }""")
        if removed_count > 0:
            dismissed = True
            print(f"  >> Removed {removed_count} blocking modal(s)")
            time.sleep(0.3)
    except Exception:
        pass

    # Strategy 2: Remove cookie/consent/GDPR overlays (never contain form inputs)
    try:
        removed = page.evaluate("""() => {
            let removed = 0;
            document.querySelectorAll(
                '[class*="cookie"], [class*="Cookie"], ' +
                '[id*="cookie"], [id*="Cookie"], ' +
                '[class*="consent"], [class*="Consent"], ' +
                '[class*="gdpr"], [class*="GDPR"]'
            ).forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width > 200 && rect.height > 100) {
                    el.remove();
                    removed++;
                }
            });
            return removed;
        }""")
        if removed > 0:
            dismissed = True
            print(f"  >> Removed {removed} cookie/consent overlay(s)")
            time.sleep(0.3)
    except Exception:
        pass

    # Strategy 3: Remove ad overlay by ID (always safe)
    try:
        removed = page.evaluate("""() => {
            let removed = 0;
            const adOverlay = document.getElementById('advertisement');
            if (adOverlay) {
                const wrapper = adOverlay.closest('[data-role="modal-wrapper"]') || adOverlay.parentElement;
                if (wrapper) { wrapper.remove(); removed++; }
                else { adOverlay.remove(); removed++; }
            }
            return removed;
        }""")
        if removed > 0:
            dismissed = True
            time.sleep(0.3)
    except Exception:
        pass

    # Strategy 4: Click close buttons on modals that do NOT contain form inputs.
    # This is the dangerous one — we must check each modal before closing it.
    modal_selectors = [
        "[data-role='modal-wrapper']",
        "[role='dialog']",
        ".modal",
    ]
    for modal_sel in modal_selectors:
        try:
            modal = page.locator(modal_sel)
            if modal.count() > 0 and modal.first.is_visible():
                # Check if this modal contains form inputs — if so, skip it
                if _has_form_inputs(page, modal_sel):
                    logger.debug("Skipping modal %s — contains form inputs", modal_sel)
                    continue
                # Safe to close — try close button inside this modal
                close_btn = modal.first.locator("button[aria-label='Close'], [class*='close']")
                if close_btn.count() > 0 and close_btn.first.is_visible():
                    close_btn.first.click(timeout=2000)
                    time.sleep(0.5)
                    dismissed = True
                    print("  >> Dismissed non-form modal overlay")
                    break
        except Exception:
            continue

    # Strategy 5: Remove orphan backdrops only if no visible form-containing
    # modals remain (the backdrop may belong to the resume upload dialog)
    try:
        has_form_modal = page.evaluate("""() => {
            const modals = document.querySelectorAll(
                '[data-role="modal-wrapper"], [role="dialog"], .modal');
            for (const m of modals) {
                if (m.getBoundingClientRect().height > 0
                    && m.querySelector('input, textarea, select, [role="combobox"]')) {
                    return true;
                }
            }
            return false;
        }""")
        if not has_form_modal:
            removed = page.evaluate("""() => {
                let removed = 0;
                document.querySelectorAll('.modal-backdrop').forEach(el => {
                    el.remove();
                    removed++;
                });
                document.body.style.overflow = '';
                document.documentElement.style.overflow = '';
                return removed;
            }""")
            if removed > 0:
                dismissed = True
                time.sleep(0.3)
    except Exception:
        pass

    return dismissed
