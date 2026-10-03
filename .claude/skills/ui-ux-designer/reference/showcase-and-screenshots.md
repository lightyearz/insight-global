# Product Showcases and Screenshot Capture

## Contents

- [Showcase section pattern](#showcase-section-pattern)
- [Annotation callouts](#annotation-callouts)
- [Lightbox](#lightbox)
- [Capturing screenshots for review or marketing](#capturing-screenshots-for-review-or-marketing)

## Showcase section pattern

For landing or feature pages that show the real product:

- Present each scene (a key screen or flow) inside a browser or device frame so it reads as "product", not as an illustration. Two co-equal scenes side by side (stacked on mobile) work better than one hero plus thumbnails when both use cases matter equally.
- One shared light/dark toggle drives **all** scenes in the section together, and themes the whole section (background, headings, body, the toggle itself), not just the images. Implementation: section-scoped `data-theme` from component state; see the `themes-and-dark-mode.md` reference.
- Swap theme screenshots by stacking both images in the same box and cross-fading opacity, so there is no layout shift and no loading flash:

```tsx
<div className="relative aspect-[16/10] overflow-hidden rounded-xl border border-border bg-surface shadow-lg">
  <Image src={scene.light} alt={scene.alt} fill sizes="(min-width: 1024px) 50vw, 100vw"
         className={`object-cover transition-opacity duration-300 ${mode === "light" ? "opacity-100" : "opacity-0"}`} />
  <Image src={scene.dark} alt="" aria-hidden="true" fill sizes="(min-width: 1024px) 50vw, 100vw"
         className={`object-cover transition-opacity duration-300 ${mode === "dark" ? "opacity-100" : "opacity-0"}`} />
</div>
```

- Only one of the two stacked images carries the `alt` text, so screen readers do not hear it twice.
- If you attach copy to the toggle, keep it understated and accurate: it is still just a theme switch, and the product behaves identically in both.

## Annotation callouts

Callouts that explain parts of a screenshot:

- Hidden by default and revealed on hover **and** on keyboard focus of the frame (`group-hover:opacity-100 group-focus-within:opacity-100`), fading out on leave. Because they only appear on demand, they may overlap the screenshot.
- `pointer-events-none` on the callout so it never blocks clicks on the frame (for example, opening the lightbox).
- Speech-bubble style reads friendlier than a box with an arrow. Make the tail a small rotated rounded square (`size-3 rotate-45 rounded-[3px]`) in the bubble colour; a sharp CSS border triangle looks harsh at this scale.
- Keep each callout to one short sentence, and keep the same information available as visible text near the section for touch users, who cannot hover.
- Respect reduced motion: switch the fade to an instant show/hide.

## Lightbox

Clicking a screenshot opens it full-screen:

- Use a dialog primitive: focus moves into it, `Esc`, backdrop click and a visible close button (with `aria-label`) all close it, and focus returns to the thumbnail.
- The trigger is a `<button>` wrapping the image (with an accessible name like "Enlarge dashboard screenshot"), not a clickable `div`.
- Show the image at its natural resolution up to the viewport (`object-contain`), on `bg-overlay`. Preload the full-size image on hover or focus of the thumbnail.
- The lightbox shows the image for the currently selected theme.

## Capturing screenshots for review or marketing

Automate captures with Playwright so they are repeatable and consistent:

- **Theme matrix:** drive the app's real theme switcher live (no reload) and capture the same screen and data in every theme and accent you ship. Capturing via the real control also verifies that it works.
- **Fresh CSS:** restart the dev server, or use a production build, before capturing after any Tailwind, token or global-CSS change; hot reload can keep serving the previous CSS and bake stale styling into the image.
- **Clean frame:** pre-dismiss cookie banners and onboarding tips by seeding their `localStorage` keys before navigation, and hide development-only overlays (framework dev indicators, debug toolbars) with an injected style tag.
- **Deterministic content:** seed or mock the data, freeze the clock, disable animations, and wait for fonts and images to load.
- **Consistent framing:** fixed viewport sizes (for example 1440x900 desktop, 390x844 mobile) and device scale factor 2 for crisp marketing images.

```ts
await page.addInitScript(() => {
  localStorage.setItem("<app>-cookie-consent", "dismissed");
});
await page.goto("/dashboard");
await page.addStyleTag({ content: "[data-dev-overlay], nextjs-portal { display: none !important; } *, *::before, *::after { animation: none !important; transition: none !important; }" });
await page.evaluate(() => document.fonts.ready);
for (const theme of ["light", "dark"] as const) {
  await page.getByRole("button", { name: "Theme" }).click();
  await page.getByRole("menuitemradio", { name: theme === "light" ? "Light" : "Dark" }).click();
  await page.screenshot({ path: `screenshots/dashboard-${theme}.png`, fullPage: false });
}
```

Adapt selectors and storage keys to the app. Commit captures used in the product (marketing pages) and regenerate them whenever the UI they show changes.
