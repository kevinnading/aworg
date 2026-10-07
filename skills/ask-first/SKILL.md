---
name: ask-first
description: The questions worth asking before building something for someone -- a short bank per kind of project, how to tell a question that changes the build from one that does not, and the defaults to use for whatever goes unasked. Use when a request to build a site, app, tool, store or automation is short or leaves out who it is for, what it must do, or where it will run.
---

# Ask first

Ask only questions whose answers change what gets built. Ask them together,
in one message, at most five, and say the default you will use for each if
there is no answer. Then build.

## Does this question change the build?

Ask it if a different answer means different files, a different data model,
a different stack, or work thrown away. Do not ask it if any answer leads to
the same first version -- pick a good default and mention it instead.

## Question banks

### Website or landing page
1. Who is it for, and what should a visitor do on it (buy, book, sign up,
   read, call)?
2. Is there existing branding: a logo, colours, fonts, a site to match?
3. What pages: one page, or which separate ones?
4. Real content to use (text, prices, photos), or write placeholder-free
   sample content?
5. Does anything need to be saved or sent: a form, orders, sign-ups?

### Online store or catalog
1. How many products, roughly, and where does the product data come from?
2. Do people pay on the site, or just browse and contact?
3. Categories, search, filters: which matter?
4. Stock, sizes or variants?
5. Who adds and edits products afterwards, and how?

### App or tool
1. Who uses it, and how many people at once?
2. The one task it must do well on day one?
3. Accounts and logins needed, or one user?
4. Where does the data live, and must it survive restarts?
5. Phone, desktop, or both?

### Automation or script
1. What starts it: a schedule, a file appearing, a button, an event?
2. What it reads and what it writes, exactly (folders, sites, accounts)?
3. What should happen when it fails: retry, skip, alert someone?
4. How often, and how much data each run?

## Defaults when unasked

Say these out loud so they can be corrected:

- Audience: the general public, on phones first.
- Stack: plain HTML, CSS and JavaScript for a site; Python with SQLite for
  anything that stores data.
- Content: real, specific sample content written for the subject -- no
  lorem ipsum, no "Product 1".
- Data: kept in a local SQLite file that survives restarts.
- Accounts: none, until asked.
- Payments: none -- browse and contact only, until asked.

## When not to ask

- The request already answers the bank's questions.
- The job is small enough that building it is faster than asking (under
  roughly ten minutes of work): build it, and offer the changes the
  questions would have raised.
- The person has said to go ahead without questions.
