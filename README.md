# Hlídání Timity

Každých 15 minut kontroluje dostupnost služeb Timity (relay, záloha mimo Cloudflare, Tim-out, zpětná vazba, web) a platnost TLS certifikátů. Při výpadku nebo končícím certifikátu založí issue a pošle e-mail vlastníkovi; po obnově issue zavře a pošle druhý e-mail.

- Skript: `hlidej.py` (jen standardní knihovna Pythonu)
- Spouštění: `.github/workflows/hlidani.yml`
- Secret repa: `MAIL_PASSWORD` (heslo schránky noreply@timity.app)
