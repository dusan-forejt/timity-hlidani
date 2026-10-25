#!/usr/bin/env python3
"""Hlídání dostupnosti služeb Timity (zdarma přes GitHub Actions).

Každých 15 minut zkontroluje adresy níže a platnost TLS certifikátů.
Stav drží v issues tohoto repa (otevřené issue = probíhající výpadek / končící certifikát),
takže e-mail přijde jen při ZMĚNĚ: výpadek začal / skončil, certifikát brzy končí / obnoven.
E-mail jde z noreply@timity.app přes SMTP (secret MAIL_PASSWORD); bez secretu se jen zakládají issues.
"""
import json, os, smtplib, socket, ssl, subprocess, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage

# (název, adresa, očekávaná odpověď) — "200" = přesně 200, "http" = jakákoli odpověď pod 500
KONTROLY = [
    ("Relay (Prodloužený dosah)", "https://relay.timity.app/key", "200"),
    ("Relay – záloha mimo Cloudflare", "https://relay-d.timity.app/key", "200"),
    ("Tim-out API", "https://api.timity.app/api/ping", "http"),
    ("Tim-out API – záloha mimo Cloudflare", "https://api-d.timity.app/api/ping", "http"),
    ("Zpětná vazba", "https://feedback.timity.app/", "http"),
    ("Web timity.app", "https://timity.app/", "http"),
    ("DEV relay", "https://dev-relay.timity.app/key", "200"),
    ("DEV relay – záloha", "https://dev-relay-d.timity.app/key", "200"),
]
CERTY = ["relay.timity.app", "relay-d.timity.app", "api-d.timity.app", "dev-relay-d.timity.app",
         "api.timity.app", "feedback.timity.app", "timity.app"]
CERT_VAROVANI_DNI = 14
REPO = os.environ.get("GITHUB_REPOSITORY", "")


def zkus(url, ocekavano):
    req = urllib.request.Request(url, headers={"User-Agent": "timity-hlidani/1"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            kod = r.status
    except urllib.error.HTTPError as e:
        kod = e.code
    except Exception as e:  # noqa: BLE001 — timeout, DNS, TLS…
        return False, f"{type(e).__name__}: {e}"
    ok = kod == 200 if ocekavano == "200" else kod < 500
    return ok, f"HTTP {kod}"


def dni_certu(host):
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=15) as s:
        with ctx.wrap_socket(s, server_hostname=host) as t:
            konec = datetime.strptime(t.getpeercert()["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    return (konec - datetime.now(timezone.utc)).days


def gh(*args):
    return subprocess.run(["gh", *args, "-R", REPO], check=True, capture_output=True, text=True).stdout


def otevrene():
    vystup = gh("issue", "list", "--state", "open", "--limit", "100", "--json", "number,title")
    return {i["title"]: i["number"] for i in json.loads(vystup)}


def mail(predmet, text):
    heslo = os.environ.get("MAIL_PASSWORD")
    if not heslo:
        print("MAIL_PASSWORD chybí, e-mail neodeslán:", predmet)
        return
    m = EmailMessage()
    m["From"] = "Timity hlídání <noreply@timity.app>"
    m["To"] = os.environ.get("MAIL_TO", "dusan@timity.app")
    m["Subject"] = predmet
    m.set_content(text)
    with smtplib.SMTP("mail.blueboard.cz", 587, timeout=30) as s:
        s.starttls(context=ssl.create_default_context())
        s.login("noreply@timity.app", heslo)
        s.send_message(m)


def main():
    cas = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if os.environ.get("TEST_MAIL") == "1":
        mail("Timity: zkušební e-mail hlídání",
             f"Toto je zkušební e-mail z hlídání služeb Timity ({cas}). Upozornění na výpadek budou chodit stejnou cestou.")
        print("zkušební e-mail odeslán")
    otevr = otevrene()
    chyby = 0

    for nazev, url, ocek in KONTROLY:
        ok, detail = zkus(url, ocek)
        if not ok:  # jedno opakování proti náhodnému výkyvu
            time.sleep(20)
            ok, detail = zkus(url, ocek)
        titul = f"🔴 Výpadek: {nazev}"
        print(("OK  " if ok else "CHYBA ") + f"{nazev} {url} {detail}")
        if not ok and titul not in otevr:
            gh("issue", "create", "--title", titul, "--body", f"Od {cas} neodpovídá {url} ({detail}).")
            mail(f"Timity: {nazev} NEODPOVÍDÁ",
                 f"{nazev} ({url}) od {cas} neodpovídá: {detail}.\n\n"
                 "Krátký výpadek se obvykle srovná sám a přijde e-mail, že služba zase běží.\n"
                 "Trvá-li déle než ~15 minut nebo se opakuje, přepošli tento e-mail do Claude (TA).")
        elif ok and titul in otevr:
            gh("issue", "close", str(otevr[titul]), "--comment", f"Zase běží od {cas} ({detail}).")
            mail(f"Timity: {nazev} zase běží", f"{nazev} ({url}) zase odpovídá od {cas} ({detail}).")
        chyby += 0 if ok else 1

    for host in CERTY:
        titul = f"⚠️ Certifikát končí: {host}"
        try:
            dni = dni_certu(host)
        except Exception as e:  # noqa: BLE001 — nedostupnost hlásí kontroly výše
            print(f"CERT {host}: nelze ověřit ({e})")
            continue
        print(f"CERT {host}: zbývá {dni} dní")
        if dni < CERT_VAROVANI_DNI and titul not in otevr:
            gh("issue", "create", "--title", titul, "--body", f"{cas}: certifikát {host} vyprší za {dni} dní.")
            mail(f"Timity: certifikát {host} končí za {dni} dní",
                 f"Certifikát {host} vyprší za {dni} dní a sám se neobnovil.\nPřepošli tento e-mail do Claude (TA).")
        elif dni >= CERT_VAROVANI_DNI and titul in otevr:
            gh("issue", "close", str(otevr[titul]), "--comment", f"{cas}: obnoveno, zbývá {dni} dní.")

    return 0 if chyby == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
