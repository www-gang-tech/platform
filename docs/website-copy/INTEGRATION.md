# Prelaunch copy in the existing editorial site

The hardware copy lives in `brain/vault/public/` as Markdown files. `gang build` renders those files through the existing studio shell (`templates/editorial.html`, `templates/home.html`, `public/shell.css`, `public/style.css`). It does not use a separate retail layout.

## Run locally

```sh
python3 cli/gang/cli.py build
python3 cli/gang/cli.py serve --host 127.0.0.1 --port 8010
```

Open `http://127.0.0.1:8010/`. The homepage pairs an introduction with the existing prototype photograph, then selects an object, a research note, and a design story. Studio introduces the founders, the working approach, and the living archive. The expanded story at `/journal/a-place-for-charging/` uses the prototype photograph and documented design rationale; no sketches, test results, or historical development sequence have been invented.

## Launch updates

**Request updates by email** is a Markdown link to `mailto:info@gang.tech`. The Updates page tells visitors to send the message. It is not a hosted form.

## Public presentation

The pages share `site-shell`, breadcrumbs, the existing footer, and Markdown content. The homepage has a responsive introduction and photograph; Studio and the design story use a narrower reading measure. Contextual links connect the object, research, and writing.

Public navigation invites visitors to **Follow the work**. Editor access remains at `/studio.html` without a public navigation link; Cart is also removed from the public navigation during prelaunch. Comment scripts load only in the post and article templates, and the cart script loads in the cart template. Editorial pages need neither script.

## Specification sheet integration — October 3, 2026

The owner supplied `GANG__Specifications (1).pdf` and confirmed **GANG–1** as the public product name. The original file is copied unchanged to `public/documents/gang-specifications.pdf`, served at `/assets/documents/gang-specifications.pdf`. Product, compatibility, setup, and press pages link to it. Page URLs and document IDs remain stable.

The current product specification now includes four zones rated up to 25 W each, a 160 W integrated supply, 120 V input, Qi2.2 with the sheet's 2.2.1 standard version, injection-moulded TPU front, die-cast milled zinc back, 4 ft extension cord, no USB-C charging ports, and the listed box contents. Compatibility preserves the sheet's named models and case conditions, distinguishing vertical magnetic attachment from flat legacy Qi charging.

The copy identifies these as development specifications. The 90-minute headline, separate iPhone 17 charging-time figures, and “24+” device total are not promoted into website claims: the sheet does not provide a shared timing test basis or a complete device/case matrix. No final-product certification or simultaneous four-device output is inferred from the sheet. The existing prototype photograph remains labelled as a prototype.

The public-content validator accepts download links only for files present in the configured public asset directory. Missing assets and paths outside that directory still fail validation.

## Typography — October 4, 2026

The supplied AMB Dual Mono Regular font is self-hosted at `/assets/fonts/AMBDualMono-Regular.otf`. Shared typography applies 16px text, weight 400, zero letter spacing, and 20px line height to headings, body copy, navigation, tables, captions, and controls. The typography partial is included in both shared and standalone public templates; semantic headings and emphasis remain in the markup.
