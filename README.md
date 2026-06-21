# 🛒 Handleliste

En enkel, delt handleliste for familien. Alle i husstanden ser samme liste, og endringer dukker opp hos alle i sanntid — uten å oppdatere siden. Bygget som en liten containerisert webapp og eksponert utenfor hjemmenettet via Cloudflare Tunnel.

## Funksjoner

- **Delt liste** — alle ser og redigerer samme handleliste.
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

| Metode   | Endepunkt           | Beskrivelse                                  |
| -------- | ------------------- | -------------------------------------------- |
| `GET`    | `/api/items`        | Hent alle varer (sortert på opprettet)       |
| `POST`   | `/api/items`        | Legg til vare — `{ "name", "added_by" }`     |
| `PATCH`  | `/api/items/{id}`   | Veksle avkryssing av en vare                 |
| `DELETE` | `/api/items/{id}`   | Slett én vare                                |
| `DELETE` | `/api/items`        | Slett alle avkryssede varer                  |
| `GET`    | `/api/stream`       | SSE-strøm med live-hendelser                 |

SSE-hendelser har formen `{ "type": "add" | "update" | "delete" | "delete_checked", ... }`.

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

Én tabell, `items`:

| Felt         | Type      | Beskrivelse                       |
| ------------ | --------- | --------------------------------- |
| `id`         | integer   | Primærnøkkel                      |
| `name`       | string    | Navn på varen                     |
| `added_by`   | string    | Hvem som la den til               |
| `checked`    | boolean   | Om varen er krysset av            |
| `created_at` | datetime  | Tidspunkt varen ble lagt til (UTC)|

Databasen ligger på Docker-volumet `db-data` (`/data/handleliste.db`) og overlever omstart av containere.

## CI/CD

[`.github/workflows/docker.yml`](.github/workflows/docker.yml) bygger og pusher backend- og frontend-images til Docker Hub ved hver push til `master`. Krever repo-secrets `DOCKER_USERNAME` og `DOCKER_PASSWORD`.

## Prosjektstruktur

```
.
├── backend/
│   ├── main.py            # FastAPI: CRUD + SSE-kringkasting
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
