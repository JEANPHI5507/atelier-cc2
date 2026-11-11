# Phone, tablet, away from home

[← Back to the README](../../README.md) · 🇫🇷 [Français](../telephone-et-tablette.md)

## Opening the workshop to your home network

```bash
uv run cc2 --control dash --reseau
```

(The service installed by `cc2 --control service installer` already does it.)

The workshop then opens to the other devices on your network, **over HTTPS on port 8443**, protected by an **access
code**. It installs on the phone like an app: icon on the home screen, full screen, and a clear message if the
workshop's machine is off. At start-up, the console prints the addresses to use:

```
Depuis le téléphone (même Wi-Fi): https://192.168.1.20:8443/lab/
Code d'accès: 123456  (note-le, il ne sera plus affiché ; `cc2 code-acces` pour le changer)
```

("From the phone (same Wi-Fi)" and "Access code: write it down, it won't be shown again".)

### Why a certificate to install

HTTPS is needed to install the app, keep the screen on and receive notifications. Since the workshop has no public
domain name, it creates its **own certificate authority** (in `.certs/`, private key readable by you only) and signs the
server certificate with it. Each device must trust this authority once. The server certificate renews itself, even if
the machine's address changes.

### Step by step

On the workshop's machine, the **Téléphone** (phone) button at the top shows the steps for Android, iPhone and
ChromeOS:

1. **Certificate (once).** A QR code downloads `atelier-cc2.crt`.
   - **Android**: Settings → Security → Encryption & credentials → Install a certificate → CA certificate.
   - **iPhone**: open the downloaded file (Settings → Profile Downloaded → Install), then **Settings → General → About →
     Certificate Trust Settings** and enable full trust for "Atelier CC2 – autorité locale".
   - Menus vary between brands: search for "certificate" in the settings.
2. **Open and install.** A second QR code opens the workshop. Enter the access code, then **Installer l'appli**
   (install the app, Android, Chrome) or **Share → Add to Home Screen** (iPhone, Safari).

From the network, the old HTTP address (`:8787`) only hands out the certificate and redirects to HTTPS.
`--sans-https` keeps a plain-HTTP workshop, without app installation.

### The access code

- 6 digits, shown **only once** at first start; only an encrypted fingerprint is kept.
- Each device asks for it once and stays signed in for 30 days. After 5 mistakes, a 5-minute wait.
- The workshop's own machine never needs it.
- `uv run cc2 code-acces` changes it and signs every device out.

## The wall tablet

An old tablet becomes the printer's screen: **Tableau** (dashboard) button in the workshop, or
`https://<workshop address>:8443/lab/tableau.html`. Same certificate and code as the phone; it installs as an app too.

- The **camera**, large, with the print's name, progress and the AI's state.
- The **print**: percentage, time left, end time, layer, current colour and upcoming colours.
- The **cross-section**: the part seen from the front, printed layers in colour, and the current layer seen from above.
- **Temperatures**, CANVAS **spools**, live **alerts** with a sound.
- **When idle**: the last print (photo, duration, cost), the month's total, maintenance due.
- **Controls**: light, pause and resume, **stop by holding your finger for 2 seconds** (no stopping by mistake).
- **Screen kept on**, **full screen**, **night mode** (dimmed from 10 pm to 7 am when nothing prints, or by hand; a
  finished print or a problem wakes it up).

It is written for old browsers and works in landscape and portrait. Tip: keep the tablet plugged in, and in its
settings choose "never turn the screen off while charging".

**ChromeOS tablet**: open `http://<workshop address>:8787/lab/ca.crt` in Chrome, then **Settings → Privacy and security →
Security → Manage certificates → Authorities → Import** (or `chrome://certificate-manager`) and tick "Trust this
certificate for identifying websites". Then open the dashboard and install it (**⋮ → Install**).

## Away from home, with Tailscale

The workshop drives a printer that heats up to 300 °C: **don't open a port on your router**. Use a private network
between your devices instead. [Tailscale](https://tailscale.com) is free for personal use and needs no router setup.

1. Install Tailscale on the **workshop's machine**:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo systemctl enable --now tailscaled     # on some servers, the service doesn't start by itself
   sudo tailscale up                          # open the link it prints to add the machine to your account
   ```
2. Install the Tailscale app on the **phone**, signed in to the same account.
3. In Tailscale's admin console, keep **MagicDNS** on: each machine then gets a name like `my-pc.tailXXXX.ts.net`.
4. **Restart the workshop.** It sees Tailscale, adds that name to its certificate and prints it at start-up:
   ```
   Hors de chez toi (Tailscale): https://my-pc.tailXXXX.ts.net:8443/lab/
   ```
5. On the phone, open this address (the certificate you already installed is enough) and install the app from it: it
   will work at home and away.

ntfy alerts then carry a link that opens the workshop through this address.

## Security in short

- Without `--reseau`, nothing is visible from the network: the workshop only listens on `127.0.0.1`.
- With `--reseau`: HTTPS, access code required (except on the machine itself), limited attempts, session in a
  protected cookie.
- Any action (start, stop, delete, change a setting) is refused if it comes from another site than the workshop.
- The printer's camera (port 8080) stays open to the whole local network: that's how the printer works.
