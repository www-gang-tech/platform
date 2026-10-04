# GANG — SEO and publishing handoff

Prelaunch is confirmed by the owner. This is a content plan, not a completed implementation or a live SEO audit. Proposed metadata is in [metadata.csv](metadata.csv).

## Search strategy

Use one clear topic per page. The homepage introduces GANG as a hardware brand; the product page answers the commercial query; support answers fit and setup questions. Do not create near-duplicate category pages for every keyword variation.

| Page | Primary intent | Language to use naturally |
| --- | --- | --- |
| Home | Understand the brand and first product | GANG, wireless charging, wall-mounted charging hub |
| Product | Evaluate this product | GANG–1, wall-mounted wireless charger, four charging zones |
| About | Learn who makes it and why | GANG hardware, industrial design, wireless charging |
| Compatibility | Determine whether it fits a device and case | GANG device compatibility, magnetic attachment, case requirements |
| Setup | Understand placement and installation | GANG setup, wall mounting, power connection |
| FAQ | Resolve remaining questions | GANG–1 questions |
| Journal | Explore the brand's design thinking | charging in the home, product design |
| Trade | Enquire about a specific project | GANG trade, retail enquiries, charging for shared spaces |

These are search-intent hypotheses drawn from the actual product, not measured keyword volumes or ranking forecasts. Before scaling editorial content, use Search Console data and actual customer questions to refine priorities. “4-in-1 charger” is ambiguous, so pair the name with “four charging zones.” Hold specific Qi2, 25 W, iPhone, Pixel, Samsung, and MagSafe targeting until corresponding claims can be supported for the final product.

Write for the person making a decision. Clear titles, helpful original information, descriptive links, and concise descriptions support discovery. There is no SEO minimum word count; do not pad these pages to reach one. [Google SEO Starter Guide](https://developers.google.com/search/docs/fundamentals/seo-starter-guide)

## Metadata and on-page content

Use the CSV's unique titles and descriptions as editorial drafts. Confirm the retail product name first. Keep a descriptive product category in the title and visible introductory sentence even when the hero headline is evocative. Titles should reflect the actual page, using the brand consistently. Search engines may generate a different title link. [Google title-link guidance](https://developers.google.com/search/docs/appearance/title-link)

Use one primary H1 for page clarity and the existing template contract; use H2s for the page's sections. Keep copy in server-rendered HTML. Do not bake headlines or essential specs into images. Use real internal links with labels such as “Check device compatibility.” Expandable details must remain accessible to visitors and present in the rendered page.

Each public page should have its final canonical URL, matching Open Graph title/description, and an approved share image. CSV paths are proposals, not already implemented routes. Confirm the production hostname; the repository currently uses `gang-platform.dev`, while the brand's recorded domain is `gang.tech`.

## A small, useful architecture

Primary navigation: Product · About · Journal · Support. Footer links provide Contact, Trade, Press, Updates, and applicable policies. Link from the homepage to the product; from product to compatibility/setup; from those guides back to product; and from relevant journal stories to the product or About.

Google uses links between pages to understand an ecommerce site's structure. Important product pages should be reachable through normal navigation. [Google ecommerce site-structure guidance](https://developers.google.com/search/docs/specialty/ecommerce/help-google-understand-your-ecommerce-site-structure)

**First release:** Home, Product, About, Contact, Updates, and applicable Privacy/Terms. Add Support, FAQ, Compatibility, and Setup when they are useful; the included prelaunch versions are interim information, not completed buying guides. Journal needs approved imagery and at least one published story. Trade and Press are optional footer destinations when their enquiry routes are staffed. Do not put thin temporary guide pages into the sitemap merely to increase page count.

**Ordering release:** Replace the product state, complete compatibility/setup, publish final shipping/returns and warranty, enable bag/checkout, and replace the relevant FAQ answers. Preserve product URL continuity through the launch.

## Existing-page disposition

The repository separates public canonical content (`brain/vault/public/`) from private brain content. Its current pages mainly describe the publishing platform. Apply retail copy to the public source used by the build after confirming the route implementation. Editing only legacy `content/` files may not update the generated site.

| Existing route/content | Proposed treatment |
| --- | --- |
| `/` | Replace the feed-led introduction with the retail homepage |
| `/products/` | For one product, link the nav directly to its detail page; retain a useful catalog if needed, or redirect only after checking existing traffic and links |
| Product detail template | Adapt for the single product and its prelaunch state |
| `/pages/about/` | Retail About becomes `/about/`; preserve platform material in documentation if still needed |
| `/pages/manifesto/` | Consolidate retail philosophy into About; archive platform manifesto in documentation |
| `/pages/features/` | Move platform features to documentation; no retail feature page |
| `/pages/contact/` | Replace with retail Contact at `/contact/` |
| `/pages/faq/` | Replace platform answers with hardware FAQ at `/support/faq/` |
| `/pages/wcag-conformance/` | Replace unverified blanket conformance language with an accurate accessibility statement |
| `/posts/` | Introduce `/journal/`; map retained articles individually |
| Existing Qi2 article/newsletter | Withdraw from retail navigation pending technical fact-check; do not reuse blanket speed/compatibility claims |
| `/projects/` and design-system demo | Keep in platform documentation, outside the retail journey |
| `/newsletters/` | Use `/updates/` for signup; retain a public archive only if there are real relevant issues |
| `/people/` and example profiles | Remove demo people from retail navigation and indexing |
| `/cart/` | Hide while prelaunch; activate with the actual ordering flow |
| Sitemap page | Regenerate from the final public routes; exclude drafts and placeholders |

For changed existing URLs, use permanent redirects only where a relevant replacement exists. Preserve useful existing content and inspect traffic/backlinks before removal. Do not redirect every retired article to the homepage. Verify status codes, canonical links, internal links, and the XML sitemap after the migration.

## Structured data

Use accurate `Organization` data for the brand and `BreadcrumbList` where the page has real breadcrumbs. Use `Article` for journal stories with truthful author and publication fields.

At prelaunch, a minimal truthful `Product` description can exist without inventing an offer, but it may not qualify for Google's product rich results. Do not insert a fake zero price, stock status, reviews, or ratings. When ordering opens, use the appropriate product/merchant markup with actual offer data. Google distinguishes product snippets from merchant listings and defines separate eligibility requirements. [Google product structured-data guidance](https://developers.google.com/search/docs/appearance/structured-data/product)

Markup must describe the visible page accurately. Schema is not a place to add stronger claims than the customer copy. Structured data does not guarantee a rich result. Validate implemented pages against the applicable requirements. [Google structured-data policies](https://developers.google.com/search/docs/appearance/structured-data/sd-policies)

## Release data still needed

The draft deliberately avoids converting development plans into customer promises. Resolve these specific inputs:

| Input | Reason / copy affected |
| --- | --- |
| Retail name: resolved as GANG–1 | Owner confirmed on October 3, 2026; public references use GANG–1 and retain `/objects/charger/` |
| Final materials/finish | June sheet specifies zinc; September notes discuss aluminum and possible zinc; affects detail captions and specs |
| Dimensions, weight, configuration | A final sale specification was not established by the reviewed material |
| Final standard, certified model, and certification status | The reviewed WPC correspondence records an application in progress; a certified subsystem does not establish a certified finished product |
| Verified output and simultaneous operation | Four zones and intended 25 W modules do not establish a four-device performance result |
| Device/case test matrix | The draft spec's broad model lists are insufficient for sale-ready compatibility promises |
| Approved mounting and safety instructions | Old inserts include instructions that conflict with the product's current description |
| Production packing list | The draft specification lists accessories, but final counts/configurations need confirmation |
| Launch availability and actual retail price | Planning values are not live offers |
| Delivery, returns, and warranty policies | Historical drafts are not enough to establish adopted customer terms |
| Monitored contact destinations and signup behavior | Form success, consent, and unsubscribe copy must match the real services |
| Privacy, terms, and correct legal entity | Required text depends on actual business and site operations |
| Approved product imagery and rights | No final retail image library was present in this checkout |

The main prelaunch story can move forward while those inputs are completed. Do not show approval labels or internal uncertainty tables in the customer journey; use the concise development state supplied in the copy.

October 3 update: the owner supplied the specification sheet for website integration. Current development specifications, materials, box contents, and the sheet's device listings are now public. Production confirmation, test results, and certification are still distinct from those stated specifications. The published Markdown takes precedence over the earlier copy drafts in this directory.

## Implementation acceptance checks

1. Verify every factual product claim against the release record and every CTA against a working destination.
2. Check page titles, descriptions, H1s, canonicals, and share previews on rendered pages, including mobile.
3. Confirm no private brain document, source note, draft, test fixture, or internal approval token enters public output.
4. Verify hero legibility, keyboard navigation, forms, error recovery, image alternatives, and reduced-motion behavior.
5. Measure real pages with their real images. Check the existing performance/markup contracts as well as Lighthouse and image budgets.
6. Test the signup end to end, including the correct success state, privacy link, and unsubscribe path.
7. Validate any structured data and submit the final sitemap in Search Console. A good audit score is not a ranking guarantee.
8. Track product visits, compatibility/setup use, completed signups, and form failures with the site's adopted privacy approach. Compare qualified signup behavior when testing headlines; do not optimize click rate alone.
