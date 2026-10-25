# Code lab: run the URL shortener, then break it

You have just designed a URL shortener on the canvas. You dragged a gateway, some replicas, a
cache, a queue and a database into place, and the checks turned green. But a canvas only
*claims* your design works. It cannot tell you whether it does.

So here is a question the canvas cannot answer. Last week someone sent you a short link in a
chat, you tapped it, and a page opened before you noticed anything. Somewhere a computer looked
up six letters and answered "go here". **What happens to your link if that computer's database
disappears?** Does it stop working? Does it get slower? Does anyone notice?

In this lab you stop answering that with a guess. You will run a real shortener on your own
laptop, stop its database with one command, and watch what the people clicking links see.

## What you are about to run

Not a toy and not a simulation. It is the same system you drew, as real programs in Docker
containers:

- a **gateway** (nginx) at the front door
- three copies of the **API** behind it (the replicas)
- **Redis**, used twice: as the cache and as the queue of click events
- a **worker** that counts the clicks
- **Postgres**, which holds every link

You need Docker installed and running, and Python with [uv](https://docs.astral.sh/uv/) for the
experiments. Then:

```bash
git clone https://github.com/ZeeshanAdilButt/system-design-labs
cd system-design-labs/labs/lab-1-url-shortener
docker compose up -d --build        # the first build takes a minute or two
```

Open <http://localhost:8080>. Make a link, press **Visit**, then press **500** under *Send
traffic*. The diagram lights up the path each request took: which replica answered, and whether
the answer came from the cache (green) or the database (orange). Everything you drew on the
canvas is now something you can click.

## Why this is more than the canvas

On the canvas, "add a cache" is a box. Here it is a Redis container with a time limit on every
entry, and you can read the line of code that asks it for an answer. The numbers below were
measured on this system, not estimated:

- A redirect that the cache can answer takes about **2 ms** when nobody else is waiting, and
  **6 ms** (p99 17 ms) with 16 requests in flight. When it has to ask the database it takes
  **15 ms** (p99 68 ms). That is the whole reason the cache exists.
- Short codes made at random start colliding after about **275,000** links. This lab uses a
  counter put through a shuffle and had **zero** collisions in a million links.
- Stop one API replica, or two: **0** redirects failed.

(p50 is the typical wait. p99 is the wait that only 1 in 100 people exceeded. The unhappy people
live in the p99.)

## Replay your design on the real stack

Your canvas design is a few settings. Write them as a small JSON, for example a design with two
replicas, no cache and no worker:

```json
{"replicas": 2, "cache": false, "worker": false}
```

From the repository folder, give it to the bridge:

```bash
uv sync --all-packages
uv run labs/lab-1-url-shortener/tools/scenario.py run '{"replicas": 2, "cache": false, "worker": false}'
```

The bridge sets those knobs on the running containers (it really stops a replica, it really
turns the cache off), sends a burst of redirects, then breaks one thing at a time: a replica,
Redis, Postgres, the worker. It prints one table. Each row is a check you also see on the canvas,
with the number it measured next to the target and the part of the lab that proves it.

You can also use the four presets, named like the designs you build first. Run them in this
order and read the table each time:

```bash
uv run labs/lab-1-url-shortener/tools/scenario.py run single_server
uv run labs/lab-1-url-shortener/tools/scenario.py run add_cache
uv run labs/lab-1-url-shortener/tools/scenario.py run add_queue
uv run labs/lab-1-url-shortener/tools/scenario.py run full_design
```

A full run takes about two minutes. Add `--quick` for one. What you should expect to see:

| Design | What changes in the table |
|---|---|
| `single_server` | Redirects are slow, and losing the only replica fails nearly every request. Losing the database fails the links too, because nothing remembers them. |
| `add_cache` | Redirects are faster, and hot links now survive the database dying. But each redirect still waits for its click to be written, so with the database down they crawl. |
| `add_queue` | Clicks are counted later by a worker, so redirects stay fast even with the database down. Still one replica, so losing it fails. |
| `full_design` | Three replicas: losing one is invisible. One check still fails, on purpose (see the third experiment). |

Speed numbers depend on your machine: judge the speed rows by comparing designs on your own
laptop, not against the targets. The other rows do not depend on speed.

## Three things to try and break

Below, `scenario.py` is short for `uv run labs/lab-1-url-shortener/tools/scenario.py`, run from
the repository folder. Keep the page open at <http://localhost:8080> and run `scenario.py reset`
first, so you start from the full design. Change one thing at a time and watch the diagram and
the status pill at the top.

### 1. Take the cache away

```bash
uv run labs/lab-1-url-shortener/tools/scenario.py apply add_cache      # cache on, one replica
uv run labs/lab-1-url-shortener/tools/scenario.py apply single_server  # cache off
```

Press **Visit** and then **500** after each. With the cache, the diagram lights green and the
hit ratio climbs. Without it, every request is orange: it goes to Postgres. *Why does the
database get slower than Redis for this job?* Because Redis answers a key lookup from memory,
and Postgres has to parse a query and read a row. Check your guess against the p50 and p99 rows
in the table, and against [part 2](part-2-the-cache).

### 2. Kill the database

```bash
scenario.py reset
docker compose stop postgres
```

Visit a link you opened a minute ago: it still redirects, from the cache. Now try to make a new
link, or open one nobody has opened yet. You get a clean error after about **2 seconds**, not a
hang. The system got worse but did not go down. Start it again with `docker compose start
postgres` and the page recovers in a few seconds.

Now do it on the `add_cache` design (`scenario.py apply add_cache`) and visit a link. It still
works, but slowly, because that design counts each click inside the redirect and the click write
waits for the dead database. *Which design would you rather be on call for?* This is the
difference the check `db_down_redirect_p99_ms` measures.

### 3. Kill Redis, and count what you lost

```bash
scenario.py reset
docker compose stop redis
```

Visit links again. They still work (slower, from the database), so nobody sees an error. But
look at the click counter on a link after sending some traffic: the clicks made while Redis was
down are gone, because the queue lives in Redis. In part 3 we measured it: **7,055 clicks
sent, 4,106 counted**, so 42% lost. That is the one check `full_design` fails, and it fails
honestly. The fix is a choice, not a trick: count clicks without a queue and pay in redirect
speed, or put the events somewhere that survives (a file, SQS). Which would you pick for a
business that charges per click?

When you are done, put everything back with `scenario.py reset`, and `docker compose down` to
stop it all (add `-v` to forget the data).

## How this maps to the checks on the canvas

| Check on the canvas | What you did here | Where the number comes from |
|---|---|---|
| A link can be made, a link redirects, a taken name is refused, unknown is a 404 | You used the page | the system's tests |
| No two links share a code | The bridge makes 200 links at once and compares the codes | [part 1](part-1-the-codes) |
| Every click is counted | You pressed **500** and watched the counter catch up | [part 2](part-2-the-cache) |
| Typical and slowest redirect time, requests per second | You compared designs | [part 2](part-2-the-cache) |
| Survives losing a replica, the cache, the database | You stopped each one | [part 3](part-3-break-it) |
| Database errors come back fast | You made a link while Postgres was down | [part 3](part-3-break-it) |
| No clicks lost when Redis fails, or when the worker stops | You stopped Redis, then the worker | [part 3](part-3-break-it) |

## Go further

The three parts each have a script that measures one question and writes a table you can read
line by line, with links from each number to the code that produced it:

1. [The codes](part-1-the-codes): where a short code comes from and why it never collides.
2. [The cache](part-2-the-cache): what Redis buys the read path.
3. [Break it](part-3-break-it): what people see when each piece dies.

There is also a version that runs on AWS-shaped services (DynamoDB and SQS, served locally by
LocalStack) with no account needed: see the lab README. The code is the same; only two settings
change.
