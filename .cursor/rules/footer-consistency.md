# Footer Consistency Rule

## Requirement

ALL pages must have the SAME footer with:
1. Copyright notice
2. Lighthouse scores (Performance, Accessibility, Best Practices, SEO)
3. Last updated timestamp

## Implementation

### Footer HTML Structure
```html
<footer>
    <p>&copy; {{ year }} {{ site_title }}. Built with GANG.</p>
    <p class="lighthouse-scores">
        <span class="score" title="Performance">⚡ <strong>100</strong></span>
        <span class="score" title="Accessibility">♿ <strong>100</strong></span>
        <span class="score" title="Best Practices">✓ <strong>100</strong></span>
        <span class="score" title="SEO">🔍 <strong>100</strong></span>
    </p>
    <p class="last-updated">
        <time datetime="{{ build_time_iso }}">Last updated: {{ build_time }}</time>
    </p>
</footer>
```

### Footer CSS
```css
footer {
    margin-top: 4rem;
    padding-top: 2rem;
    border-top: 1px solid var(--color-border);
    text-align: center;
    color: var(--color-muted);
    font-size: 0.9rem;
}

.lighthouse-scores {
    margin-top: 0.5rem;
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
    font-size: 0.85rem;
    justify-content: center;
}

.lighthouse-scores .score {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
}

.lighthouse-scores strong {
    font-weight: 600;
    color: #1a1a1a;
}

.last-updated {
    margin-top: 0.5rem;
    font-size: 0.8rem;
    opacity: 0.8;
}

.last-updated time {
    font-style: italic;
}
```

## Templates That Must Include This Footer

- ✅ base.html
- ✅ post.html
- ✅ page.html
- ✅ list.html
- ✅ product.html
- ✅ products-list.html
- ✅ newsletter.html
- ✅ newsletters-list.html

## Variables Required

All templates must receive:
- `year` - Current year
- `site_title` - Site title from config
- `build_time` - Human-readable timestamp
- `build_time_iso` - ISO format timestamp

## Enforcement

This is a QUALITY BAR. Any page without this exact footer structure fails validation.

## Rationale

- **Consistency:** Users expect the same footer everywhere
- **Trust:** Lighthouse scores build credibility
- **Transparency:** Last updated shows content freshness
- **Branding:** Copyright + "Built with GANG"

