# No Rounded Corners Rule

## Requirement

**NO rounded corners** on components unless explicitly specified in a prompt.

## Implementation

```css
/* WRONG */
.component {
    border-radius: 8px;  /* ❌ Don't add this */
}

/* CORRECT */
.component {
    border: 1px solid var(--color-border);  /* ✅ Square corners */
}
```

## CSS Variables

```css
:root {
    --border-radius: 0;  /* Default to zero */
}
```

## When Rounded Corners ARE Allowed

Only add `border-radius` when:
1. User explicitly requests it in a prompt
2. Functional requirement (e.g., circular avatar)
3. Design system specifies it

## Enforcement

- All new components: Square corners by default
- Buttons: Square (no border-radius)
- Cards: Square (no border-radius)  
- Images: Square (no border-radius)
- Inputs: Square (no border-radius)

## Exceptions

- Theme toggle switch: Functional circular design
- Avatar images: IF explicitly requested

## Rationale

- Clean, minimal aesthetic
- Reduces CSS complexity
- Consistent with brutalist/modernist design
- User maintains control over visual decisions

