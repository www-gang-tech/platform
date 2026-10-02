# GANG — page copy

Draft for editorial and design review. “Customer copy” blocks contain proposed website language. Notes, tables of missing release data, and visual instructions are for the team. Primary navigation: **Product · About · Journal · Support**. The logo links home. Use **Get updates** before launch; add **Bag** when ordering opens.

## 01 / Home

**Route:** `/`  
**Purpose:** Make the object desirable and understandable in the first screen.  
**Visual:** A full-width photograph of the actual product mounted in a considered interior. Show its scale and a compatible phone in use.

### Customer copy

**Eyebrow:** GANG 4-in-1

**H1: Power has a place.**

A wall-mounted wireless charging hub with four charging zones. Designed for the spaces we share.

**Primary CTA:** Explore GANG 4-in-1  
**Secondary CTA:** Get launch updates

**H2: Charging, off the counter.**

Bring charging onto the wall. Leave more room for everything else.

**Link:** See the design

**H2: Four places to recharge.**

One shared place for compatible devices. At home. At work. Within reach.

**Link:** Check compatibility

**H2: Everyday objects deserve attention.**

GANG makes technology for the spaces we live in. We begin with charging.

**Link:** About GANG

**Closing line:** Follow what comes next.  
**Supporting copy:** Product news, design notes, and launch updates from GANG.  
**CTA:** Get updates

### Design notes

Use four substantial visual moments, with the last line functioning as the global signup. Keep the initial category sentence visible without a click. Place “See the design” at the product page's design section. Avoid duplicating the entire product page on the homepage.

## 02 / Product

**Route:** `/products/gang-4-in-1/`  
**Purpose:** Explain the product, establish desire, and resolve fit questions.  
**Visual:** Front, side, rear, in-use, and installation context. Product photography carries the page; specifications use real text.

### Customer copy

**H1: GANG 4-in-1**

Wall-mounted wireless charging. Four charging zones. One considered object.

**State:** In development  
**Primary CTA:** Get launch updates  
**Secondary link:** Check compatibility

**H2: Make room.**

Move everyday charging onto the wall. Keep the counter for the things you want there.

**H2: A place to come together.**

Four charging zones bring compatible devices to one shared place.

**H2: Considered from every side.**

The front. The profile. The way it meets the wall. Each is part of the design.

**H2: Know what fits.**

Check your device and case together. Wireless charging support and magnetic attachment both matter when charging on a vertical surface.

**Link:** Device compatibility

**H2: Find its place.**

Consider where you charge, the space around the product, and access to power. Start with the setup information before choosing a location.

**Link:** Setup and placement

**H2: Product details**

| Detail | Description |
| --- | --- |
| Product | GANG 4-in-1 |
| Format | Wall-mounted wireless charging hub |
| Charging zones | Four |
| Charging connection | Wireless; no USB-C charging ports |
| Availability | In development |

Final specifications and supported devices will be published before orders open.

**H2: Questions, answered.**

**What does 4-in-1 mean?**  
Four wireless charging zones in one hub. Check the compatibility information for supported devices.

**Can I charge by USB-C?**  
No. This product is designed for wireless charging and does not include USB-C charging ports.

**Is it completely wireless?**  
Devices charge wirelessly. The hub itself still needs a connection to power.

**When can I order?**  
Join launch updates for availability news.

**Closing CTA:** Get launch updates

### Launch replacement: purchase panel

Activate only with final pricing, inventory, compatibility, and fulfillment data. Replace the development state and signup CTA with:

- **Price:** `{{ price_with_currency }}`
- **Finish label, if variants exist:** Finish
- **Selected finish:** `{{ approved_finish_name }}`
- **Availability:** `{{ actual_stock_status }}`
- **Dispatch:** Ships `{{ confirmed_dispatch_window }}`
- **Primary button:** Add to bag
- **Helpful links:** Check compatibility · Setup and placement · Shipping and returns

Do not invent a finish selector for a single-finish product. Keep price, stock, any preorder status, and dispatch timing visible beside the button. “Preorder” replaces “Add to bag” only if an actual preorder offer exists.

### Launch replacement: specification section

Replace the development table with final values for dimensions, product weight, materials/finish, input voltage/frequency, power connection, charging standard, per-zone output, simultaneous output behavior, approved device/case combinations, installation requirements, box contents, and issued certifications. Include a downloadable final manual alongside HTML information.

Conditional performance wording after validation: **“Up to {{ verified_per_zone_watts }} W per charging zone with supported devices.”** Add the actual test conditions and power-sharing behavior. A power supply's rating is not wireless charging output. Do not infer a four-device charging speed from a single-zone maximum.

### Launch replacement: box contents

**H2: In the box**

Show the verified production contents in one overhead photograph. Label each item with its name and quantity. Populate the list from the final packing list; do not use the draft accessory list as an order promise.

## 03 / About

**Route:** `/about/`  
**Purpose:** Establish a clear point of view and a real company behind the product.  
**Visual:** An object in its setting, followed by a real studio/prototype photograph. Credit people or collaborators only when the specific role is confirmed.

### Customer copy

**H1: Everyday objects deserve attention.**

GANG is a consumer hardware company focused on wireless charging.

We think the technology you live with should receive the same attention as the room around it: how it works, how it feels, and where it belongs.

**H2: We begin with charging.**

Charging is part of daily life. Its place in the home deserves thought.

Our first product brings four wireless charging zones into one wall-mounted object. A practical function, considered as part of the room.

**H2: Function gives it form.**

We start with a use. Then consider the shape, the surface, and the experience around it. Every detail should have a reason to be there.

**H2: Why GANG?**

The name comes from electrical gang boxes and the idea of devices charging together. A reference to what connects us, built into the object itself.

**H2: Founded by Frank Godchaux and Daniel Hirunrusme.**

A shared interest in useful technology and thoughtful design.

**CTA:** Explore GANG 4-in-1

## 04 / Journal

**Route:** `/journal/`  
**Purpose:** Give the brand a voice through real design work.  
**Visual:** A sparse editorial index with one image per story, honest publication dates, and descriptive article titles.

### Customer copy

**H1: Journal**

Objects, decisions, and the work behind GANG.

**Article 1:** A place for charging  
**Summary:** Why we began with the wall.  
**Link:** Read A place for charging

**Article 2:** What belongs in the room  
**Summary:** Our approach to the technology we live with.  
**Link:** Read What belongs in the room

### Editorial note

The two finished drafts follow. Publish this index once at least one approved story has its real images. Add future engineering stories only when the underlying work can be shown and substantiated. No empty “coming soon” article cards or fabricated interviews.

## 05 / Journal: A place for charging

**Route:** `/journal/a-place-for-charging/`  
**Visual:** A room-scale installation photograph, a closer view, then the product profile. No invented testing or customer testimony.

### Customer copy

**H1: A place for charging**

A room is shaped by small decisions. Where a light falls. Where a chair sits. What stays on the counter.

Charging needs a place, too.

With GANG 4-in-1, we began at the wall. Four wireless charging zones become one object, giving compatible devices a shared place to recharge.

**H2: The room is part of the design.**

A product is experienced in context. Its size, position, and relationship to the things around it matter as much as its appearance on a white background.

That is why we want to show GANG in a room. How it sits against the wall. What space it leaves around it. How it fits into an ordinary day.

**H2: A clear purpose.**

The idea is simple: bring charging together and move it off the counter.

The details need to be equally clear. Which devices fit. Where the hub can be installed. How it connects to power. Those answers belong alongside the photographs.

**CTA:** Explore GANG 4-in-1

## 06 / Journal: What belongs in the room

**Route:** `/journal/what-belongs-in-the-room/`  
**Visual:** Product details paired with genuine development images. Show real design decisions without claiming a particular manufacturing process is final.

### Customer copy

**H1: What belongs in the room**

We give thought to the objects we live with. A lamp. A table. A speaker. Each has a function, a presence, and a place.

We believe everyday charging deserves that same consideration.

**H2: Start with use.**

For GANG, design begins with a practical question: where should charging happen?

Our first answer is a wall-mounted hub with four wireless charging zones. One place for compatible devices, considered in relation to the space around it.

**H2: Give each detail a reason.**

The shape should serve the function. The surface should belong to the object. The information should help someone use it.

This is the approach we want to carry through GANG, from the hardware to the way we explain it.

**H2: Make the everyday worth considering.**

We begin with something familiar. Then give it our attention.

**CTA:** About GANG

## 07 / Support

**Route:** `/support/`  
**Purpose:** Help people get to an answer quickly. This page prioritizes navigation over atmosphere.

### Customer copy

**H1: Support**

Find the information you need about GANG 4-in-1.

**Device compatibility**  
Check what to look for in your device and case.  
**Link:** View compatibility

**Setup and placement**  
Plan where the product will go.  
**Link:** View setup information

**Common questions**  
The product, availability, and how to stay informed.  
**Link:** Read the FAQ

**Still need help?**  
Tell us what you need to know.  
**CTA:** Contact GANG

### Launch additions

Add **Orders and shipping**, **Returns**, **Warranty**, and **Manual and safety information** when the corresponding services and approved documents exist. Link the manual directly, showing language, version, and file size. Do not let a download replace useful HTML support information.

## 08 / Compatibility

**Route:** `/support/compatibility/`  
**Purpose:** Resolve fit questions accurately, including magnetic attachment and case requirements.

### Customer copy — prelaunch

**H1: Device compatibility**

The right fit starts with your device and case.

GANG 4-in-1 is being developed for magnetic wireless charging. The final list of supported devices and cases will be published before orders open.

**H2: Check the model.**

Use your device's exact model name when checking compatibility.

**H2: Check the case.**

A case is part of the charging setup. Magnetic attachment and wireless charging support both need to be considered.

**H2: Check the position.**

Compatibility needs to cover the way a device is used on the product, including attachment to the vertical charging surface.

**H2: Have a particular device in mind?**

Send us its model name and the case you use.

**CTA:** Ask about compatibility

### Launch replacement

Change the introduction to: **“Find your device and case below before ordering.”** Replace the prelaunch notice with a tested matrix:

| Device model | Case requirement | Supported orientation | Charging output/conditions | Status |
| --- | --- | --- | --- | --- |
| Populate from release testing | Exact tested requirement | Exact supported use | Verified value and conditions | Supported / Not supported / Not tested |

“Not tested” must not look like “Not supported.” Add a visible last-verified date. Do not infer compatibility from a logo, a manufacturer's entire range, or a generic Qi claim. Do not claim Apple Watch support. Link the same matrix from the product page and purchase panel.

## 09 / Setup and placement

**Route:** `/support/setup/`  
**Purpose:** Explain the installation experience through an approved demonstration and matching instructions.

### Customer copy — prelaunch

**H1: Find its place.**

GANG 4-in-1 is designed to bring wireless charging onto the wall.

Installation requirements and the complete setup guide will be published before orders open.

**H2: See it in your space.**

Think about where you reach for your devices, the space around the hub, and access to power.

**H2: Planning a location?**

Tell us about the space you have in mind.

**CTA:** Ask about setup

### Launch replacement

**H1: Set up GANG 4-in-1**  
**Intro:** Follow the guide for your product and mounting configuration. Read the installation and safety instructions before you begin.

**Section labels:** Before you begin · What you need · Installation · First charge · Care · Troubleshooting

Populate each section from the release manual and match the video to that exact hardware version. Show outlet/wall requirements, power connection, clearance, included versus additional tools, and who can perform installation. Installation steps and electrical advice cannot be reconstructed from the conflicting draft inserts in the brain.

**Video link:** Watch the setup guide  
**Download link:** Download the manual  
**Help link:** Get setup help

Only render these links when their approved destinations are available. Include captions and a text version of the video instructions.

## 10 / FAQ

**Route:** `/support/faq/`  
**Purpose:** Give concise answers to actual product questions. Use visible headings or accessible expandable sections.

### Customer copy

**H1: Questions about GANG**

**H2: What is GANG?**  
GANG is a consumer hardware company focused on wireless charging. Our first product is a wall-mounted charging hub with four charging zones.

**H2: What does 4-in-1 mean?**  
Four wireless charging zones in one hub. It describes the number of zones; supported devices will be listed in the compatibility guide.

**H2: Which devices will it charge?**  
The final supported-device list is being developed. Check the compatibility page for the information available before ordering.

**H2: Does it have USB-C charging ports?**  
No. GANG 4-in-1 is designed for wireless charging.

**H2: Does the hub need power?**  
Yes. Wireless charging describes the connection to your device. The hub itself still needs a power connection.

**H2: How is it installed?**  
The product is designed for wall mounting. The complete installation requirements and setup guide will be published before orders open.

**H2: When will it be available?**  
Join launch updates for availability news. A shipping date has not been announced here.

**H2: Can I ask about a commercial space?**  
Yes. Contact us with the type of space, location, approximate quantity, and timing.

**CTA:** Contact GANG

### Launch note

Replace availability, compatibility, and installation answers with current facts and direct links. Add price, delivery regions, dispatch timing, returns, and warranty answers from the same release data used elsewhere. Do not create conflicting policy summaries.

## 11 / Contact

**Route:** `/contact/`  
**Purpose:** A direct route to a real response; no invented email addresses or response-time promises.

### Customer copy

**H1: Contact GANG**

For product questions, press, retail, and projects.

**Fields:** Name · Email · What can we help with? · Message  
**Topics:** Product question · Setup and compatibility · Press · Retail and projects · Something else  
**Optional field when relevant:** Order number

**Message helper:** Include your device model for compatibility questions, or a few details about the project you have in mind.

**Button:** Send message

**Success:** Your message has been sent.  
**Failure:** Your message couldn't be sent. Your text is still here. Please try again.  
**Email error:** Enter a valid email address.  
**Message error:** Add a message so we can help.

### Implementation note

Route to a confirmed, monitored inbox. Preserve entered text on failure. Display “sent” only after successful delivery. Add a privacy link and factual processing notice consistent with the actual form service. Add a backup email only after its mailbox is confirmed.

## 12 / Trade and projects

**Route:** `/trade/`  
**Purpose:** Invite relevant conversations without inventing wholesale terms, installation services, or existing customers.

### Customer copy

**H1: A place in your project.**

Considering GANG for a home, workplace, or shared space?

Tell us about the setting, the number of units you're considering, and your timing.

**H2: Retail enquiries**

Introduce your store and the way you would present GANG.

**H2: Design enquiries**

Share the project, location, and charging needs.

**CTA:** Start a conversation

### Design note

Use one real product-in-context image. Do not imply the pictured property is a customer. Label conceptual placements accurately. Route the CTA to Contact with the relevant topic selected.

## 13 / Press

**Route:** `/press/`  
**Purpose:** Give editors a factual description and a route to approved assets.

### Customer copy

**H1: GANG press**

Product information, images, and enquiries.

**H2: About GANG**

GANG is a consumer hardware company founded by Frank Godchaux and Daniel Hirunrusme. Beginning with wireless charging, the company brings thoughtful industrial design to technology used in the home and workplace. Its first product, GANG 4-in-1, is a wall-mounted wireless charging hub with four charging zones.

**H2: Images and product information**

Contact us for press materials and product enquiries.

**CTA:** Contact press

### Publication note

Add downloadable press images and a fact sheet when approved. Supply image credits, permitted usage, version date, final product name, and a verified availability statement. Do not invent press coverage, awards, or review quotes.

## 14 / Updates

**Route:** `/updates/`  
**Purpose:** A clear, low-friction prelaunch conversion.

### Customer copy

**H1: Follow what comes next.**

Product news, design notes, and launch updates from GANG.

**Field:** Email address  
**Button:** Get updates  
**Helper:** Unsubscribe at any time.

**Consent:** Send me product news, design notes, and launch updates from GANG.

**Success, single opt-in:** You're on the list.  
**Success, double opt-in:** Check your inbox to confirm your email.  
**Invalid email:** Enter a valid email address.  
**Failure:** We couldn't add your email. Please try again.

### Current prelaunch implementation

The live site does not use a hosted form. **Request updates by email** opens a prewritten message to `info@gang.tech`. The page tells visitors to send the message; opening the email app is not treated as a completed subscription. Helper copy: “Opens your email app with a request to info@gang.tech. Send the message to request updates. You can unsubscribe by email at any time.”

The form fields and success states above are retained for a later hosted signup. Set `prelaunch.signup_url` when that service exists.

### Implementation note

Use the success state matching the actual subscription system. Link the real privacy policy. Subscription never implies a reservation, guaranteed stock, priority allocation, or early purchase access. Use this same copy for the global footer signup.

## 15 / Shipping and returns

**Route:** `/shipping-returns/`  
**State:** Release with ordering, after the actual policy is settled. No prelaunch placeholder page in navigation.

### Customer copy

**H1: Shipping and returns**

Delivery information and how to request a return.

**H2: Delivery**  
**Labels:** Shipping destinations · Shipping cost · Dispatch time · Estimated delivery · Tracking

**H2: Returns**  
**Labels:** Return window · Item condition · Return shipping · Refund timing · Exclusions

**H2: Need help with an order?**

Send your order number and a short description of what you need.

**CTA:** Get order help

### Required policy content

Populate every label from the adopted policy before publishing. Specify when the return period starts, any fees, who pays return shipping, how to initiate a return, and what happens to original delivery charges. No free-shipping, 30-day-return, or guaranteed-delivery claim has been assumed. This is the page's copy framework; operative terms remain an explicit input dependency.

## 16 / Warranty

**Route:** `/warranty/`  
**State:** Release with ordering and the adopted warranty.

### Customer copy

**H1: Warranty**

Coverage and support for your GANG product.

**H2: Your coverage**  
**Labels:** Coverage period · What is covered · What is excluded · Available remedies · Regional terms

**H2: Make a claim**

Contact us with your product, proof of purchase, and a description of the issue.

**CTA:** Get warranty help

### Required policy content

Add the complete adopted warranty, eligibility, service process, and applicable rights language. Earlier draft warranty terms and contact details conflict with the current materials; do not silently select one. No service duration or repair promise has been invented here.

## 17 / Accessibility

**Route:** `/accessibility/`  
**Purpose:** Offer an actionable way to report access problems without asserting unaudited conformance.

### Customer copy

**H1: Accessibility**

If something on this website prevents you from finding information or completing a task, please tell us.

Include the page, what you were trying to do, and the issue you encountered. You can also include your browser or assistive technology if it helps explain the problem.

**CTA:** Report an accessibility issue

### Publication note

Route to a monitored contact method. Add a conformance statement only after the actual site has been evaluated, with scope, date, limitations, and contact details. The existing platform's performance targets are not proof of the retail site's accessibility.

## 18 / Privacy and terms

**Routes:** `/privacy/` and `/terms/`  
**State:** Actual policies required for the services enabled on the site.

### Customer copy — privacy introduction

**H1: Privacy**

How GANG collects, uses, and manages personal information through this website.

### Customer copy — terms introduction

**H1: Terms**

Terms for using this website and purchasing from GANG.

### Required content

Place the applicable, adopted policy beneath each introduction. Supply the correct legal entity, effective date, contact method, data/service details, and terms matching the checkout. For a prelaunch site with no purchasing terms, use “Terms for using this website.” These introductions are not complete legal policies; the brain does not establish final website terms or actual data flows.

## 19 / Bag and commerce states

**Route:** `/cart/`  
**State:** Activate with ordering; keep out of the search index.

### Customer copy

**H1: Your bag**

**Empty:** Your bag is empty.  
**Empty CTA:** Explore GANG 4-in-1

**Line-item labels:** Product · Finish · Quantity · Price  
**Actions:** Update quantity · Remove  
**Summary labels:** Subtotal · Shipping · Tax · Total  
**Primary CTA:** Continue to checkout

**Added confirmation:** GANG 4-in-1 added to your bag.  
**Confirmation actions:** View bag · Continue exploring

**Out of stock:** Currently unavailable.  
**Out-of-stock CTA:** Get availability updates

**Quantity error:** Only {{ available_quantity }} available. Update your quantity to continue.  
**Checkout failure:** We couldn't open checkout. Your bag is saved. Please try again.

### Implementation note

Only show “Your bag is saved” if persistence is verified; otherwise use “We couldn't open checkout. Please try again.” Display shipping/tax language that matches the actual checkout and market. Never imply a cart item is reserved unless it is. Use restock consent matching the notification service rather than subscribing a customer to unrelated marketing.

## 20 / Not found

**Route:** `/404.html`  
**State:** Return HTTP 404 and keep out of the search index.

### Customer copy

**H1: Page not found.**

The page may have moved, or the address may be incorrect.

**Primary CTA:** Go to GANG  
**Secondary link:** Contact us

## Global footer

**Brand line:** Considered objects. Everyday use.

**Product:** GANG 4-in-1 · Compatibility · Setup  
**Company:** About · Journal · Contact · Trade · Press  
**Support, when available:** FAQ · Shipping and returns · Warranty  
**Utility:** Privacy · Terms · Accessibility

**Copyright:** © {{ current_year }} {{ confirmed_copyright_holder }}

Keep this compact, with grouped links and generous spacing. Link only to actual, useful pages. Do not add generic trust badges, invented payment marks, unissued certifications, or unsupported service promises.
