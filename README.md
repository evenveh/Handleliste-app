# 🛒 Handleliste

En enkel, delt handleliste for familien — og for flere husstander i samme app. Alle i en husstand ser samme liste, og endringer dukker opp hos alle i sanntid — uten å oppdatere siden. Bygget som en liten containerisert webapp og eksponert utenfor hjemmenettet via Cloudflare Tunnel.

## Funksjoner

- **Flere husstander** — hver husstand har sin egen liste og en hemmelig invitasjonskode (f.eks. `K7QM-3XTP`). Del koden eller en invitasjonslenke (`/?join=KODE`) for å la andre bli med. Én enhet kan være med i flere husstander og bytte mellom dem.
- **Delt liste** — alle i husstanden ser og redigerer samme handleliste.
- **Sanntid** — varer som legges til, krysses av eller slettes oppdateres live hos alle via Server-Sent Events (SSE).
- **Kryss av uten å slette** — avkryssede varer flyttes til en «Kjøpt»-seksjon, og kan fjernes samlet.
- **Hvem la til varen** — hvert navn lagres lokalt i nettleseren første gang du åpner appen.
- **Optimistisk UI** — avkryssing reagerer umiddelbart, med tilbakerulling hvis serveren feiler.
- **PWA-vennlig** — manifest, ikoner og `theme-color` for å legge til på hjemskjerm.

## Teknologi

| Lag        | Teknologi                                                        |
| ---------- | --------------------------------------------------------------- |
| Frontend   | Svelte 4 + Vite, servert som statiske filer via nginx          |
| Backend    | Python FastAPI + SQLAlchemy 2, kjørt med Uvicorn               |
| Database   | SQLite (lagret på et Docker-volum)                             |
| Sanntid    | Server-Sent Events (`/api/stream`)                            |
| Eksponering| Cloudflare Tunnel (`cloudflared`)                             |
| Drift      | Docker Compose + GitHub Actions (bygg/push av images)         |

## Arkitektur

```
                 Internett
                    │
              Cloudflare Tunnel
                    │
        ┌───────────┴───────────┐
        │   cloudflared (CF)     │
        └───────────┬───────────┘
                    │  internal-nettverk
        ┌───────────┴───────────┐
        │  frontend (nginx)      │  :3000 → :80
        │  - serverer Svelte-SPA │
        │  - proxyer /api/ ──────┼──┐
        └────────────────────────┘  │
                                     ▼
                        ┌────────────────────────┐
                        │  backend (FastAPI)      │  :8000
                        │  - CRUD + SSE broadcast │
                        │  - SQLite på /data      │
                        └────────────────────────┘
```

nginx serverer den ferdigbygde Svelte-appen og proxyer alle `/api/`-kall videre til backend-containeren. For at SSE skal fungere er buffering slått av i [nginx.conf](frontend/nginx.conf). Backenden holder en liste over tilkoblede klienter og kringkaster hver endring til alle.

## API

Alle endepunkter ligger under `/api`.

Alle endepunkter for varer er knyttet til en husstand via koden i stien. Koden er det eneste som gir tilgang, så den bør behandles som et passord. Små bokstaver og manglende bindestrek godtas.

| Metode   | Endepunkt                              | Beskrivelse                                  |
| -------- | -------------------------------------- | -------------------------------------------- |
| `POST`   | `/api/households`                      | Opprett husstand — `{ "name" }` → `{ "name", "code" }` |
| `GET`    | `/api/households/{code}`               | Hent husstand (brukes for å bli med)         |
| `PATCH`  | `/api/households/{code}`               | Endre navn — `{ "name" }`                    |
| `GET`    | `/api/households/{code}/items`         | Hent alle varer (sortert på opprettet)       |
| `POST`   | `/api/households/{code}/items`         | Legg til vare — `{ "name", "added_by" }`     |
| `PATCH`  | `/api/households/{code}/items/{id}`    | Veksle avkryssing av en vare                 |
| `DELETE` | `/api/households/{code}/items/{id}`    | Slett én vare                                |
| `DELETE` | `/api/households/{code}/items`         | Slett alle avkryssede varer                  |
| `GET`    | `/api/households/{code}/stream`        | SSE-strøm med live-hendelser for husstanden  |

SSE-hendelser har formen `{ "type": "add" | "update" | "delete" | "delete_checked" | "household", ... }` og sendes bare til klienter i samme husstand.

## Oppsett og kjøring

### Forutsetninger

- Docker og Docker Compose
- En Cloudflare Tunnel med tilhørende token (for ekstern tilgang)

### 1. Lag en `.env`-fil

Tunnel-tokenet leses av `cloudflared`. Opprett en `.env` i prosjektroten:

```env
TUNNEL_TOKEN=<ditt-cloudflare-tunnel-token>
```

> `.env` er git-ignorert og skal aldri sjekkes inn — den inneholder en hemmelighet.

### 2. Start alt

```bash
docker compose up -d
```

Dette starter tre tjenester: `backend`, `frontend` og `cloudflared`. Frontend blir tilgjengelig lokalt på [http://localhost:3000](http://localhost:3000), og via Cloudflare-domenet ditt utenfor hjemmenettet.

`docker-compose.yml` bruker ferdigbygde images fra Docker Hub (`evenve/handleliste-*`). Vil du bygge lokalt fra kildekoden, kan du peke `build:` mot `./backend` og `./frontend` i stedet for `image:`.

### Lokal frontend-utvikling

For rask iterasjon på UI:

```bash
cd frontend
npm install
npm run dev
```

Vite-serveren kjører på [http://localhost:5173](http://localhost:5173). Merk at `/api/`-kall forventer en kjørende backend (start den f.eks. via `docker compose up backend`).

## Datamodell

`households`:

| Felt         | Type      | Beskrivelse                                   |
| ------------ | --------- | --------------------------------------------- |
| `id`         | integer   | Primærnøkkel                                  |
| `name`       | string    | Navn på husstanden                            |
| `code`       | string    | Unik invitasjonskode (8 tegn, lagret uten `-`) |
| `created_at` | datetime  | Tidspunkt husstanden ble opprettet (UTC)      |

`items`:

| Felt           | Type      | Beskrivelse                       |
| -------------- | --------- | --------------------------------- |
| `id`           | integer   | Primærnøkkel                      |
| `household_id` | integer   | Husstanden varen tilhører         |
| `name`         | string    | Navn på varen                     |
| `added_by`     | string    | Hvem som la den til               |
| `checked`      | boolean   | Om varen er krysset av            |
| `created_at`   | datetime  | Tidspunkt varen ble lagt til (UTC)|

Databasen ligger på Docker-volumet `db-data` (`/data/handleliste.db`) og overlever omstart av containere.

### Oppgradering fra versjonen uten husstander

Ved første oppstart migreres databasen automatisk: `items` får kolonnen `household_id`, og alle eksisterende varer flyttes til en ny husstand kalt «Vår husstand». Koden skrives til loggen:

```bash
docker compose logs backend | grep migrering
```

Finner du ikke loggen lenger, kan du hente koden direkte fra databasen:

```bash
docker compose exec backend python -c "import sqlite3; print(sqlite3.connect('/data/handleliste.db').execute('select name, code from households').fetchall())"
```

Skriv inn koden i appen (eller åpn `/?join=KODE`) på hver enhet, så ser dere den gamle lista igjen. Navnet kan endres i appen.

## CI/CD

[`.github/workflows/docker.yml`](.github/workflows/docker.yml) bygger og pusher backend- og frontend-images til Docker Hub ved hver push til `master`. Krever repo-secrets `DOCKER_USERNAME` og `DOCKER_PASSWORD`.

## Prosjektstruktur

```
.
├── backend/
│   ├── main.py            # FastAPI: husstander, CRUD, SSE og migrering
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.svelte     # Hele appen (UI + logikk)
│   │   └── main.js
│   ├── public/            # Ikoner, manifest, service worker
│   ├── nginx.conf         # Statisk servering + /api-proxy (SSE-vennlig)
│   ├── vite.config.js
│   └── Dockerfile         # Bygger SPA og pakker den i nginx
├── docker-compose.yml     # backend + frontend + cloudflared
└── .env                   # TUNNEL_TOKEN (ikke i git)
```
