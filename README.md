# System design labs

[![verify](https://github.com/ZeeshanAdilButt/system-design-labs/actions/workflows/verify.yml/badge.svg)](https://github.com/ZeeshanAdilButt/system-design-labs/actions/workflows/verify.yml)

Classic system design problems, built as small systems you can run, click and break on your
laptop. Each lab is a real stack in Docker (a load balancer, replicas, a cache, a queue, a
database) with a web page to poke it, plus measured experiments that show *why* each piece is
there. Every number the READMEs quote links back to the line of code that produced it.

This is a growing series. Every lab runs locally with plain Docker, and where it makes sense
it also runs on AWS-shaped services (DynamoDB, SQS and friends) served by
[LocalStack](https://www.localstack.cloud/), so you can compare the two without an AWS account.

## Labs

| Lab | What you build and learn |
|---|---|
| [Lab 1 · URL shortener](labs/lab-1-url-shortener) | A shortener that survives its own failures. Where short codes come from and why they never collide, what a cache buys the read path, how clicks get counted without slowing redirects, and what users see when a replica, Redis, the worker or the database dies. Three parts: the codes, the cache, break it. |

![Share of clicks counted, by what was stopped](labs/lab-1-url-shortener/part-3-break-it/chart-clicks.svg)

Start with the [lab 1 README](labs/lab-1-url-shortener): it has a 101 of every word the parts
use (replica, cache, queue, p50/p99, at-least-once) and the architecture on one page.

## Layout

```
labs/
  lab-1-url-shortener/
    README.md                start here: the 101, the architecture and all three parts
    docker-compose.yml       the whole system: gateway, 3 API replicas, Redis, Postgres, worker
    docker-compose.aws.yml   the same system on LocalStack (DynamoDB + SQS)
    system/                  the code that runs inside the containers (and its tests)
    part-1-the-codes/        README, script, results.md, charts, test
    part-2-the-cache/
    part-3-break-it/
toolkit/                     shared tools every lab reuses
tools/                       verify.py (all checks) and charts.py (draws the charts)
```

## Run it

You need [Docker](https://docs.docker.com/get-docker/) and, to run the experiments,
Python 3.12+ with [uv](https://docs.astral.sh/uv/). From this folder:

```bash
cd labs/lab-1-url-shortener
docker compose up -d --build        # first build takes a minute or two
```

Open <http://localhost:8080>. Shorten a link, visit it, fire 500 redirects at it and watch
the diagram light up. Then run an experiment from the repository folder:

```bash
uv sync --all-packages
uv run labs/lab-1-url-shortener/part-2-the-cache/the_cache.py --quick
```

Add `--quick` for a shorter run. Each part prints its tables and saves them to `results.md`
in its folder. Stop everything with `docker compose down` (add `-v` to forget the data).

## Run it on AWS services (locally)

```bash
cd labs/lab-1-url-shortener
docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d --build
```

The links now live in DynamoDB and the click events travel through SQS, both served by
LocalStack. The API, the worker and the page are the same containers: only two environment
variables changed. See [the lab README](labs/lab-1-url-shortener#run-it-on-aws-services-locally).

## The toolkit

| Tool | What it does |
|---|---|
| [sdl-load](toolkit/sdl-load) | A small keep-alive HTTP client and percentiles, fast enough that the lab scripts measure the system and not themselves |

## Check everything

```bash
./verify              # lint, strict types, all tests, the stack, every lab part
./verify --quick      # the same with short runs
./verify --no-docker  # skip the parts that need Docker
```

On Windows, run `./verify` from Git Bash, or `.\verify.ps1` in PowerShell. CI runs
`./verify --quick` on Ubuntu on every push.

## Related

[systems-performance-challenges](https://github.com/ZeeshanAdilButt/systems-performance-challenges)
looks at why systems get slow and how to measure it. [distributed-systems-challenges](https://github.com/ZeeshanAdilButt/distributed-systems-challenges)
looks at what goes wrong when machines crash, stall and retry.

## License

MIT
