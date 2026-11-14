# Alerts

[← Back to the README](../../README.md) · 🇫🇷 [Français](../alertes.md)

The workshop watches the printer **even when no page is open**: it only needs to be running (as a service, it always
is). Every event goes into the log (the bell at the top of the workshop).

## What is reported

| Alert | When |
|---|---|
| Print started / resumed | at the start, after a pause |
| Print paused | pause requested, or by the printer |
| **Out of filament** | empty or cut spool, with what to do |
| **Print finished** | with a camera photo, and a "Faire le bilan" (review) button |
| **Plate cold: you can take the part off** | after a finished print, when the plate drops below 35 °C |
| Print stopped | stopped before the end |
| **Printer error** | with the explanation of the official error code and what to do |
| The printer reports a problem | an anomaly during the print |
| **Printer unreachable** / reachable again | no news during a print |
| Suspicious print / **Failure detected** | the camera AI has a doubt / is sure (automatic pause if enabled) |
| Camera frozen | the camera no longer changes picture (a known defect of some firmware versions) |
| Spool almost empty / new spool / spool put back | under 100 g left, another spool detected in the CANVAS, a spool seen before put back with its weight |
| Maintenance due | a task in the maintenance log is due |

(In the English interface, and on the phone once English is chosen, the alerts are in English.)

## On an open page

In the workshop and on the tablet: a message, a sound and a vibration (can be turned off). On a computer, the system
notification if you allow it. The tablet wakes its screen in night mode for a finished print, a cold plate or a problem.

## On the phone, even with the app closed: ntfy

Web page notifications don't get through when the app is closed. For that, the workshop sends its important alerts
(everything except plain information) to **[ntfy](https://ntfy.sh)**, a free notification service.

**Note**: the alert's text then goes over the Internet (through the ntfy.sh server, or your own if you host one). It
only contains the print's name and the event, no image.

1. Install the **ntfy** app on the phone (Android: Play Store or F-Droid; iPhone: App Store).
2. In the workshop, open the bell, section **Alertes sur le téléphone, appli fermée** (phone alerts, app closed), and
   click **Activer** (enable): the workshop picks a hard-to-guess topic (like `cc2-4f9a…`) and shows it.
3. **Ouvrir dans ntfy** (open in ntfy, from the phone) subscribes the app to that topic; otherwise, in ntfy: **+** and
   type it. Then **Envoyer un test** (send a test).

By hand, it's one line of `config.toml` (your own ntfy server works too, always over `https://`):

```toml
[alertes]
ntfy = "https://ntfy.sh/my-hard-to-guess-topic"
```

Notifications carry a link that opens the workshop, and the end-of-print one a **Faire le bilan** (review) button. The
link uses the Tailscale address if there is one (see [Phone, tablet, away from home](phone-and-tablet.md)), otherwise
the home address.

The topic is only secret by its length: don't share it. To turn it off: **Désactiver** (disable) in the bell.
