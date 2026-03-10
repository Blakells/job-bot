"""Browser session management, screenshots, and overlay dismissal."""

import time
from pathlib import Path

import requests

from job_bot.config import BROWSERBASE_API_KEY, BROWSERBASE_PROJECT, ATS_PLATFORMS, COOKIE_DIR


class BrowserSessionError(Exception):
    """Raised when a browser session cannot be created."""
    pass


def detect_ats_platform(url):
    """Detect which ATS platform a URL belongs to."""
    url_lower = url.lower()
    for pattern, platform in ATS_PLATFORMS.items():
        if pattern in url_lower:
            return platform
    return "unknown"


def get_session_path(platform):
    """Get the path to saved browser session for an ATS platform."""
    COOKIE_DIR.mkdir(parents=True, exist_ok=True)
    return COOKIE_DIR / f"{platform}_session.json"


def has_saved_session(platform):
    """Check if we have a saved browser session for this ATS."""
    return get_session_path(platform).exists()


def save_browser_session(context, platform):
    """Save browser cookies/session state for reuse."""
    path = get_session_path(platform)
    COOKIE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        context.storage_state(path=str(path))
        print(f"  >> Session saved for {platform}")
    except Exception as e:
        print(f"  !! Could not save session: {e}")


def create_session(browser_mode="local"):
    """
    Create a browser session.

    Args:
        browser_mode: "local" or "cloud" (Browserbase)

    Returns:
        (session_id, connect_url) tuple

    Raises:
        BrowserSessionError if cloud session creation fails
    """
    if browser_mode == "local":
        print("  >> Starting local browser...")
        return "local", "local"

    print("  >> Starting cloud browser...")
    if not BROWSERBASE_API_KEY or not BROWSERBASE_PROJECT:
        raise BrowserSessionError(
            "Browserbase keys not set. Use --local or set BROWSERBASE_API_KEY"
        )

    resp = requests.post(
        "https://www.browserbase.com/v1/sessions",
        headers={"x-bb-api-key": BROWSERBASE_API_KEY, "Content-Type": "application/json"},
        json={"projectId": BROWSERBASE_PROJECT, "browserSettings": {"stealth": True}},
        timeout=30,
    )
    data = resp.json()
    session_id = data.get("id")
    if not session_id:
        raise BrowserSessionError(f"Session creation failed: {data}")

    connect_url = (
        data.get("connectUrl")
        or f"wss://connect.browserbase.com?apiKey={BROWSERBASE_API_KEY}&sessionId={session_id}"
    )
    print(f"  >> Session: {session_id}")
    return session_id, connect_url


def end_session(session_id):
    """Close a browser session."""
    if session_id == "local":
        print("  >> Browser closed")
        return
    try:
        requests.delete(
            f"https://www.browserbase.com/v1/sessions/{session_id}",
            headers={"x-bb-api-key": BROWSERBASE_API_KEY},
            timeout=10,
        )
    except Exception as e:
        print(f"  !! Session cleanup error: {e}")
    print("  >> Session closed")


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
                '.cc-window', '#onetrust-banner-sdk',
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


def dismiss_overlays(page):
    """
    Dismiss modal overlays, dialogs, backdrops, and advertisements
    that block interaction with the form underneath.
    """
    dismissed = False

    # Strategy 1: Press Escape
    try:
        page.keyboard.press("Escape")
        time.sleep(0.5)
    except Exception:
        pass

    # Strategy 2: Click close/X buttons inside modal dialogs
    close_selectors = [
        "[data-role='modal-wrapper'] button[aria-label='Close']",
        "[data-role='modal-wrapper'] [class*='close']",
        "[data-role='dialog'] button[aria-label='Close']",
        ".modal button[aria-label='Close']",
        ".modal .close",
        "[role='dialog'] button[aria-label='Close']",
        "[role='dialog'] [class*='close']",
        "[aria-label='Close']",
        "button.close",
    ]
    for sel in close_selectors:
        try:
            btn = page.locator(sel)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click(timeout=2000)
                time.sleep(0.5)
                dismissed = True
                print("  >> Dismissed modal overlay (close button)")
                break
        except Exception:
            continue

    # Strategy 3: Click the backdrop to close
    if not dismissed:
        backdrop_selectors = [
            "[data-role='backdrop']",
            "[data-evergreen-dialog-backdrop]",
            ".modal-backdrop",
            ".overlay",
        ]
        for sel in backdrop_selectors:
            try:
                backdrop = page.locator(sel)
                if backdrop.count() > 0 and backdrop.first.is_visible():
                    backdrop.first.click(position={"x": 5, "y": 5}, timeout=2000)
                    time.sleep(0.5)
                    dismissed = True
                    print("  >> Dismissed modal overlay (backdrop click)")
                    break
            except Exception:
                continue

    # Strategy 4: Remove blocking overlays via JavaScript
    try:
        removed = page.evaluate("""() => {
            let removed = 0;

            document.querySelectorAll(
                '[data-role="modal-wrapper"], ' +
                '[data-role="backdrop"], ' +
                '[data-evergreen-dialog-backdrop], ' +
                '.modal-backdrop, ' +
                '[class*="modal-overlay"], ' +
                '[class*="dialog-backdrop"]'
            ).forEach(el => {
                el.remove();
                removed++;
            });

            const adOverlay = document.getElementById('advertisement');
            if (adOverlay) {
                const wrapper = adOverlay.closest('[data-role="modal-wrapper"]') || adOverlay.parentElement;
                if (wrapper) { wrapper.remove(); removed++; }
                else { adOverlay.remove(); removed++; }
            }

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

            document.body.style.overflow = '';
            document.documentElement.style.overflow = '';
            return removed;
        }""")
        if removed > 0:
            dismissed = True
            print(f"  >> Removed {removed} blocking overlay(s)")
            time.sleep(0.5)
    except Exception:
        pass

    return dismissed
