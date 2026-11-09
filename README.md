# Staff Scheduling

Monthly shift planning for hospital stations and their jumper pool. Staff administrators check employees and monthly inputs, generate a schedule that keeps the working-time rules, review it and publish it to TimeOffice.

Developed at RWTH Aachen University with St. Marien-Hospital Düren and Pradtke GmbH.

- **Webapp**: Next.js, in German, for staff administrators
- **API**: FastAPI, owning the domain rules and the TimeOffice adapter
- **Solver**: Google OR-Tools CP-SAT, with an independent schedule check

## Demo version

This branch is the demo version for the practice partner's laptops. It plans one fictional station (`api/app/demo.py`: nine professionals, three of them part-time, one assistant and two trainees) for every month of 2026 and 2027, without TimeOffice, and solves every schedule with Gurobi in a fixed 20 seconds (`SOLVER_MAX_TIME_SECONDS` in `.env`). What is entered lives in memory until the API restarts. Downloads are only `input.json` and `result.json`, to load a saved schedule again; publishing to TimeOffice is not offered. The full version lives on the `gurobi_full` branch.

Every laptop needs **its own** Gurobi WLS license in `.secrets/gurobi.lic`: an academic WLS license allows two sessions at once, and each running app holds one. The laptop also needs internet while it solves, since WLS checks the license online.

## Quickstart

You need [Docker with Compose](https://docs.docker.com/compose/install/) and [just](https://github.com/casey/just#installation). Put the laptop's Gurobi WLS license into `.secrets/gurobi.lic`, then run from the repository root:

```sh
just run
```

Open the webapp at <http://localhost:3000> and the API reference at <http://localhost:8000/docs>. Stop with `just stop`. On Windows, use Git Bash or WSL.

## Documentation

Read the [online documentation](https://combirwth.github.io/StaffScheduling/), or serve it locally with `just docs`.

- [Quickstart](docs/source/getting-started/quickstart.md) and [installation](docs/source/getting-started/installation.md)
- [Using the app](docs/source/user-guide/index.md) and its [planning rules](docs/source/user-guide/rules.md)
- [Architecture](docs/source/architecture/index.md) and [glossary](docs/source/glossary.md)
- [Development checks](docs/source/development/checks.md)
- [Example schedules](docs/source/validation/examples.md) and [limitations](docs/source/validation/index.md)
