---
name: web-project
description: How to build a small website or web application end to end — planning the pages, writing them, serving them, and checking they actually work. Use when the owner asks for a site, a web app, a landing page, or anything that will be viewed in a browser.
---

# Building a web project

A procedure, not a template. The point is the order and the checking, not the
markup.

## Plan before writing anything

Write the tasks down with `add_tasks` first. A small site is four or five
tasks, not twenty:

1. the pages themselves, named
2. the stylesheet, if there is more than one page
3. serve it
4. check it actually answers

Name the pages in the task detail. "Build the site" is a task you cannot pick
up later; "index.html, about.html, contact.html, sharing style.css" is.

## Write the pages

Delegate this to the **builder** worker unless the site is a single small
file. The builder writes files and cannot run anything, which is exactly the
scope this step needs.

Give it everything in the task: the exact filenames, what each page contains,
and that every page links to every other page and to the stylesheet. A worker
cannot see your conversation.

Keep each page modest. A page beyond a few hundred lines will not fit in one
tool call and gets cut off part way — write it in appended pieces or split it.

## Put them in a folder

Not loose in the workspace root. `site/` or the project's own name, so that
serving it serves the site rather than everything the Aworg has ever made.

## Serve it

Use `start_process`, never `execute_command`. A server does not exit, and
`execute_command` waits for things to exit, so it will simply hang until it
times out.

Give the interpreter's full path — the one in the machine facts you were
given, not a bare `python`, which on Windows is usually a Store stub that
fails.

    start_process(command='<full python path> -m http.server 8000', cwd='site')

Port 8000 is the conventional choice and is what the Application pane looks
for. If it is taken, `list_processes` will show you what you already have
running; stop that rather than picking a new port.

## Check it, properly

This is the step that is worth more than the rest put together.

Delegate to the **checker** worker. It has `http_request` and cannot change
anything, so its report is evidence rather than a repair. Ask it to fetch
every page and report the status codes.

A server process existing is not the same as a site working. The process can
be up while the pages 404 because they are in the wrong directory. Only a
200 from each page tells you the thing you are about to claim.

Do not mark the task done before that comes back.

## Let it tell you when it breaks

For a server you wrote. A stock `python -m http.server` is not your code and
cannot report; anything you wrote that keeps running should.

Every process `start_process` starts is already handed two environment
variables. There is nothing to wire up and no key to ask anyone for:

    AWORG_LOG_URL      where to POST
    AWORG_LOG_TOKEN    the value of the X-Aworg-Token header

A report is JSON: what happened, how badly, where, and the detail around it,
plus the application's own name so an Aworg running two things can tell them
apart.

    {"summary": "Could not reach the price feed", "severity": "error",
     "where": "/checkout", "detail": "...", "application": "shop"}

For `severity` use the word the language already uses — `info`, `warning`,
`error`, `critical`. They land on the Living Log's own three levels.

Put this in the task you give the builder, along with everything else. A
worker cannot see your conversation, so a helper you only thought about is a
helper that does not get written.

    import json, os, urllib.request

    def report(summary, severity="error", where="", detail=""):
        url = os.environ.get("AWORG_LOG_URL")
        if not url:
            return
        body = json.dumps({
            "summary": summary, "severity": severity, "where": where,
            "detail": detail, "application": "<this application's name>",
        }).encode()
        try:
            urllib.request.urlopen(
                urllib.request.Request(url, data=body, headers={
                    "Content-Type": "application/json",
                    "X-Aworg-Token": os.environ.get("AWORG_LOG_TOKEN", ""),
                }),
                timeout=2,
            ).close()
        except Exception:
            pass

Three things about it are deliberate and should survive into whatever gets
written. It does nothing when the variable is absent, so the program still
runs outside this Aworg. It swallows its own failures, because a program that
crashes while reporting a crash has made the morning worse. And the timeout
is short, so a busy Aworg cannot hang a request that was only being polite.

Report what is wrong: the exceptions you catch, a dependency that will not
connect, a job that gave up. Not every request. A report per request is a
second access log, and an owner learns within a day to stop reading the pane.

## Then prove the channel works

A helper that was written is not a helper that works. The token can be wrong,
the URL can be mistyped, and the `except` that hides its own failure hides a
typo exactly as well as it hides an outage.

So make it report once, on purpose, at a level you can see:

    report("Reporting test", severity="warning", where="startup")

Then call `list_concerns`. The entry should be there, under
`application:<name>`. If it is not, the channel is not connected — check the
helper before you go looking at anything else.

Close it with `resolve_concern` once you have seen it, saying it was a test.
Leaving it open puts a concern in the owner's pane that nothing is wrong
with.

This is the same rule as checking the pages. A 200 from each page, and an
entry you have actually read. Until then the application does not report, it
merely contains code that was supposed to.

## When the owner asks for changes

Use `edit_file`, not `write_file`. Rewriting a whole page to change one line
means reproducing every other line from memory, and some of them will come
back subtly different.

The server keeps running while you edit — static files are read per request,
so the change is live on the next refresh. There is no need to restart it,
and restarting it needlessly is how you end up with two servers fighting over
a port.

## Content that claims to be current

If the site is about anything described as latest, current or recent, fetch
it with `http_request` rather than writing what you remember. Your training
stopped at some point and you cannot tell from the inside how long ago that
was. A page confidently listing last year's facts as this year's is worse
than one that says less.
