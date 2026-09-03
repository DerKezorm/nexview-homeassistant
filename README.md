# Nexview for Home Assistant

Brings [Nexview](https://nexview.nexapps.dev) into Home Assistant: what is
waiting, what is running, whether the instances behind it still answer - and a
way to approve or reject a request without opening Nexview at all.

## What you get

**Sensors** for waiting requests, requests in progress, failures over the last
seven days, open findings by severity, open tickets, and how full the library
is. All of them keep history, so a graph over a month costs nothing extra.

**Events** in three groups: requests, storage and operations. Each one is an
event entity, so it shows up in the automation editor without a template.

**Actions** to approve, reject, defer or cancel a request.

**Only what your key may do.** Nexview hands out named access keys whose rights
follow the account they belong to, and a key can additionally be marked read
only. The integration asks what a key may do and creates only what fits - a
personal key produces a handful of entities, an operator's key the lot. Nothing
grey, nothing that answers 403 when pressed.

## Setting it up

1. In Nexview, open your profile and create an access key under **Access
   keys**. Give it a name you will recognise later, for instance
   `Home Assistant`. Copy it once - Nexview never shows it again.
2. In Home Assistant, add the **Nexview** integration, enter the address and
   paste the key.

That is all. If your key may configure Nexview, the integration also registers
itself as a notification target over there, so Nexview calls Home Assistant
instead of being asked every half minute. It does that by itself, including the
confirmation code Nexview requires - nothing to copy between two windows.

If Nexview cannot reach Home Assistant, everything still works, just slower,
and a repair notice says so rather than leaving you to wonder why events are
late.

## Approving from your phone

The reason this exists. Nexview tells Home Assistant that somebody asked for
something, your phone shows it with two buttons, and the answer goes straight
back:

```yaml
automation:
  - alias: Nexview request waiting
    triggers:
      - trigger: event.received
        entity_id: event.nexview_requests
        options:
          event_type: pending
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "{{ trigger.event.data.title }}"
          message: "{{ trigger.event.data.body }}"
          data:
            actions:
              - action: NEXVIEW_APPROVE
                title: Approve
              - action: NEXVIEW_REJECT
                title: Reject
```

The two buttons are wired up with a second automation that listens for
`mobile_app_notification_action` and calls `nexview.approve_request` or
`nexview.reject_request`.

## Requirements

Nexview 0.30.0 or newer. Older versions are turned away during setup with a
sentence explaining why - the integration needs an endpoint that tells it what
a key is allowed to do, and that arrived in 0.30.0.

## Installation

Until this is in the HACS default list, add it as a custom repository:

1. HACS, three dots, **Custom repositories**
2. Repository `DerKezorm/nexview-homeassistant`, category **Integration**
3. Install, restart Home Assistant, then add the integration

## Known limitations

- **Child profiles do not appear.** Nexview knows child accounts as
  sub-profiles of their parents, and their names and wishes deliberately stay
  out of a database that records everything forever.
- **The push needs an operator key.** Notification targets are an
  administrator's business in Nexview, so a personal key polls instead of being
  called. Everything else works the same.
- **One entry per account.** The same Nexview may be added twice with two
  different keys; the same account twice is refused.

## Development

Home Assistant does not run on Windows. On Linux, or in WSL:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/pytest
```

The `custom_components/nexview/api` package must never import from
`homeassistant` - a test enforces that. It is the part that will become
`python-nexview` on PyPI when this integration goes for inclusion in the Home
Assistant core, and that move should cost an import line, not a rewrite.
