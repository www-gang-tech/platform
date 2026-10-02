# Prelaunch copy in the existing editorial site

The hardware copy lives in `brain/vault/public/` as Markdown files. `gang build` renders those files through the existing studio shell (`templates/editorial.html`, `templates/home.html`, `public/shell.css`, `public/style.css`). It does not use a separate retail layout.

## Run locally

```sh
python3 cli/gang/cli.py build
python3 cli/gang/cli.py serve --host 127.0.0.1 --port 8010
```

Open `http://127.0.0.1:8010/`. Pages should look like the current studio site: a file, rendered as Markdown, in the existing header and footer.

## Launch updates

**Request updates by email** is a Markdown link to `mailto:info@gang.tech`. The Updates page tells visitors to send the message. It is not a hosted form.

## What stayed the same

Navigation, `site-shell`, breadcrumbs, editorial headers, and `.markdown-body` styling are the current website. New pages were added as Markdown, not as a new visual system.
