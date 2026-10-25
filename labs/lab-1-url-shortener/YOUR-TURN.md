# Your turn: lab 1, the URL shortener

You have read about this system and watched it run. Now you do things to it, on your own, and
find out for yourself. Nine tasks, in three parts. Each one starts from a question, asks you to
make a guess, and lets the system tell you whether you were right.

> **Try first. Solutions live in [solutions/](solutions).** Each task has a file there
> (`solutions/T1.md`, `solutions/T2.md`, and so on) with the answer, why it works and what the
> check should show. They are kept apart on purpose so you do not see one by accident. Open one
> only after you have tried, or after you have been stuck for a good while. Being wrong first is
> the point: a guess you wrote down and got wrong teaches more than an answer you read.

## How a task works

Every task has the same four parts:

1. **Goal**: what you are trying to understand or build, in plain words.
2. **Predict first**: write your guess in a notes file (or on paper) *before* you run anything.
   One line is enough, and a number is better than "it will be slower". This is the part people
   skip and it is the part that teaches.
3. **What to do**: directions, not the answer.
4. **Check yourself**: a command, and what to look for in its output.

There are four kinds of task:

| Kind | What you do |
|---|---|
| **Predict and measure** | Guess a number, then measure it |
| **Change one thing** | Turn one setting, watch what moves, then explain why |
| **Fix a planted problem** | A small piece of code has a bug put in on purpose. Find it, fix it, turn the tests green |
| **Build a missing piece** | A piece the real system does not have yet. Build it until its tests go green |

| Task | Part | Kind | Goal in one line |
|---|---|---|---|
| [T1](#t1-how-soon-do-random-codes-repeat) | 1 · The codes | Predict and measure | Feel how soon random short codes repeat |
| [T2](#t2-block-size-one) | 1 · The codes | Change one thing | See what handing out ids in blocks saves the database |
| [T3](#t3-a-shuffle-that-is-not-a-shuffle) | 1 · The codes | Fix a planted problem | Find why two links get the same code |
| [T4](#t4-switch-the-cache-off) | 2 · The cache | Predict and measure | Put a number on what the cache buys |
| [T5](#t5-the-link-that-exists-but-answers-404) | 2 · The cache | Fix a planted problem | Find why a new link answers 404 |
| [T6](#t6-stop-the-worker) | 3 · Break it | Predict and measure | Watch clicks queue up and catch up |
| [T7](#t7-the-clicks-that-vanish) | 3 · Break it | Fix a planted problem | Find where clicks go when the database blinks |
| [T8](#t8-a-circuit-breaker-for-the-database) | 3 · Break it | Build a missing piece | Turn a 2 second wait into an instant error |
| [T9](#t9-a-breaker-that-sends-one-scout) | 3 · Break it | Build a missing piece | Let one request test Redis, not all of them |

The ids (`T1` to `T9`) never change, so you can refer to a task by its id.

## Before you start

Everything runs from the repository folder, with Docker running and the stack up:

```bash
docker compose -f labs/lab-1-url-shortener/docker-compose.yml up -d --build
uv sync --all-packages
```

Two tools you will use again and again:

- **The ruler**: `uv run labs/lab-1-url-shortener/your-turn/redirect_timer.py` makes some links,
  opens them 2,000 times through the gateway and prints how many failed, how many came from the
  cache, the typical wait (p50), the slow wait (p99) and how many clicks are waiting to be
  counted. Add `--requests 500`, `--concurrency 32` or `--links 10` to change it. The numbers
  move a little every run, so compare shapes, not decimals.
- **The reset**: `uv run labs/lab-1-url-shortener/tools/scenario.py reset` puts the stack back
  to the lab's own design. Run it whenever a task has changed a setting.

Five of the tasks (T3, T5, T7, T8 and T9) are code exercises. Their files are in
[your-turn/](your-turn): a starter file `tN_*.py` for you to edit and a `test_tN_*.py` that
checks your work. **Do not edit the test files.** The tests are red when you start. That is the
point. These exercises are small copies, so they never touch the running system (the one
optional exception is the last step of T8, which says so). To run all of them, or one:

```bash
uv run pytest labs/lab-1-url-shortener/your-turn           # every exercise, red to start with
uv run pytest labs/lab-1-url-shortener/your-turn -k t3     # just one
```

A plain `uv run pytest` skips this folder, so the repository's own checks stay green while
your exercises are not finished.

---

## Part 1 · The codes

Background: [part 1 README](part-1-the-codes).

### T1 How soon do random codes repeat?

**Goal.** Get a feel for the birthday problem [the surprise that a repeat comes far sooner than
you would think]. A short code has to be different for every link. What if we just picked codes
at random?

**Predict first.** Random 5 character codes can take 916,132,832 different values. After how
many links do you expect the *first* repeated code? Pick one: hundreds, thousands, tens of
thousands, hundreds of thousands, millions. Write down one number. Then do the same for 6
characters (56.8 billion values).

**What to do.** Run part 1 in its short form (it needs no Docker) and read its first table.

```bash
uv run labs/lab-1-url-shortener/part-1-the-codes/the_codes.py --quick
```

Find your 5 and 6 character rows. Run it a second time. Then write two sentences: why is the
real number so much smaller than "about a billion", and why is it different on the second run?

**Check yourself.** In the table "When does the first collision happen?", compare your guess with
the *links until first repeat (median)* column and with the formula column next to it. Count how
many times too high or too low you were (a factor, like "10 times too high").

**Stuck?** Think about how many *pairs* of links exist, not how many links.

### T2 Block size one

**Goal.** See what "ids in blocks of 1,000" saves the database, by taking the saving away.

**Predict first.** Each API replica normally reserves a block of 1,000 ids in one trip to
Postgres and hands them out from memory. If you set the block size to 1, each new link needs its
own trip. The shared counter in Postgres (a *sequence* called `link_id_blocks`) moves forward on
every trip. Before you run anything, write down how far you expect that counter to move after
you make 10 links with the default block size, and after 10 links with block size 1.

**What to do.**

1. Look at the counter, make 10 links, look again. Use the ruler to make the links:

   ```bash
   docker compose -f labs/lab-1-url-shortener/docker-compose.yml exec postgres psql -U shortener -d shortener -c "SELECT last_value FROM link_id_blocks"
   uv run labs/lab-1-url-shortener/your-turn/redirect_timer.py --links 10 --requests 10
   docker compose -f labs/lab-1-url-shortener/docker-compose.yml exec postgres psql -U shortener -d shortener -c "SELECT last_value FROM link_id_blocks"
   ```

2. Change one thing, then repeat step 1:

   ```bash
   uv run labs/lab-1-url-shortener/tools/scenario.py apply '{"block_size": 1}'
   ```

3. Put it back with `scenario.py reset`.

Now explain, in your own words and with the "trips to the database" table in part 1 beside you,
what happened. Then answer one more question: look at the `CREATE SEQUENCE` line in
[init.sql](system/db/init.sql). With a block size of 1, how much of each reserved block gets used?

**Check yourself.** Subtract the two `last_value` readings in each case. Your explanation should
be able to say how many trips each case made.

**Stuck?** The counter does not move by 1 per trip. Find out how much it moves by.

### T3 A shuffle that is not a shuffle

**Goal.** Fix a planted bug. [`your-turn/t3_shuffle.py`](your-turn/t3_shuffle.py) is a copy of the
code that turns a counter value into a code. The real one never repeats a value. This copy does,
so two links would get the same code.

**Predict first.** Before you read the code: out of the first 50,000 counter values, how many
different outputs do you expect from a working shuffle? And from this broken one: all 50,000, or
fewer? Write both numbers.

**What to do.** Run the tests and read why they fail. Then read the file. `unshuffle` is correct
and runs the shuffle backwards, so compare what one round of `shuffle` does with what one round
of `unshuffle` undoes. Fix `shuffle`.

**Check yourself.**

```bash
uv run pytest labs/lab-1-url-shortener/your-turn -k t3
```

Red at the start (the test that counts different outputs tells you how many it got). Green when
you are done. Then compare your first guess for the broken version with the number the failing
test printed.

**Stuck?** Whatever one round does to the two halves, you must be able to get both of the old
halves back from the two new ones.

---

## Part 2 · The cache

Background: [part 2 README](part-2-the-cache).

### T4 Switch the cache off

**Goal.** Find out what the cache really buys, by taking it away.

**Predict first.** With the cache off, every redirect reads Postgres. Write down three guesses:
out of 2,000 redirects, how many reach Postgres with the cache on and how many with it off;
whether the typical wait (p50) changes, and by how much; and how big the difference between two
runs of the *same* setup is (run-to-run noise). Is the cache's effect on the wait bigger or
smaller than that noise on your laptop?

**What to do.**

```bash
uv run labs/lab-1-url-shortener/your-turn/redirect_timer.py                      # cache on (baseline)
uv run labs/lab-1-url-shortener/tools/scenario.py apply '{"cache": false}'
uv run labs/lab-1-url-shortener/your-turn/redirect_timer.py                      # cache off
uv run labs/lab-1-url-shortener/tools/scenario.py reset
```

Run each setup at least three times and write every p50 and p99 down. Then repeat with
`--concurrency 1` (nobody waiting in line) and `--concurrency 16`. Compare what you see with the
tables in [part 2](part-2-the-cache#the-results). If your numbers disagree with them, say why
that could be.

**Check yourself.** The cache-off report shows `answered from the cache: 0%` and no failures;
the baseline shows close to 100%. Every redirect that is not "from the cache" was a read of
Postgres, so that line is your answer to the first guess. For the waits, compare your three
guesses with your own table of runs.

**Stuck?** A cache protects two things: the person waiting, and the database. Which of the two
does your table show most clearly?

### T5 The link that exists but answers 404

**Goal.** Fix a planted bug in the make-a-link path. In
[`your-turn/t5_create_path.py`](your-turn/t5_create_path.py), a link can be saved in the database
and still answer "no such link" for half a minute.

**Predict first.** Someone opens `/launch` before it exists, then you create `launch`, then
someone opens it again. What do you expect to see on that last open, and for how long? Why would
the system remember the first answer at all? (The "unknown codes are cached too, for 30 s" row
in the [lab README's table of choices](README.md#choices-and-what-each-one-trades-away) may
help.)

**What to do.** Run the tests, find the line where the sequence goes wrong, and fix `make_link`.
Read the second test before you write the fix: some fixes that satisfy the first test break the
second.

**Check yourself.**

```bash
uv run pytest labs/lab-1-url-shortener/your-turn -k t5
```

Three tests, all green. Then say in one sentence why the cache write has to happen where you put
it and not somewhere else.

**Stuck?** There are two places the cache could be told about the new link. Only one of them is
safe when the name turns out to be taken.

---

## Part 3 · Break it

Background: [part 3 README](part-3-break-it).

### T6 Stop the worker

**Goal.** Watch the click queue do its job: redirects carry on while clicks wait, then the counts
catch up.

**Predict first.** You stop the worker and open links 1,000 times. Write down: how many of the
redirects will fail; how many clicks will be waiting in the queue afterwards; and how long, after
you start the worker again, until the queue is empty (seconds, minutes?).

**What to do.**

```bash
docker compose -f labs/lab-1-url-shortener/docker-compose.yml stop worker
uv run labs/lab-1-url-shortener/your-turn/redirect_timer.py --requests 1000
curl -s http://localhost:8080/api/stats
docker compose -f labs/lab-1-url-shortener/docker-compose.yml start worker
curl -s http://localhost:8080/api/stats        # repeat this every second or two
```

(`curl` is on Windows 10 and later. In PowerShell write `curl.exe`.) Look for `click_backlog` in
the stats. Then answer: would a user have noticed anything while the worker was down? What would
change if each redirect wrote its click to the database before answering?

**Check yourself.** The ruler shows `failed: 0` and a backlog close to 1,000. After the restart
`click_backlog` falls to 0. Compare each of your three guesses.

**Stuck?** The ruler's last line already tells you the backlog; the stats call shows how it falls.

### T7 The clicks that vanish

**Goal.** Fix a planted bug. [`your-turn/t7_click_counter.py`](your-turn/t7_click_counter.py) is a
click counter like the worker's. When the database blinks, some clicks are never counted, even
after it is back. Part 3 found this same bug in the real system once.

**Predict first.** The queue hands each event out once. If the counter reads a batch of 500 clicks
and the database write fails, where are those 500 clicks now? Out of 1,200 clicks, how many do
you expect to be counted if the database fails on the first two tries and works afterwards?

**What to do.** Run the tests, read the failing assertion, and work out where the failed batch
goes. Fix `step`. Remember the rule: a click may be counted twice after a crash, but never zero
times.

**Check yourself.**

```bash
uv run pytest labs/lab-1-url-shortener/your-turn -k t7
```

Both tests green. Then compare with the way the real worker does it in
[worker.py](system/shortener/src/shortener/worker.py#L27) and note one thing that is the same
and one thing that differs.

**Stuck?** `step` is called again and again by a loop. What does the loop need to find the second
time?

### T8 A circuit breaker for the database

**Goal.** Build a missing piece. Part 3's honest limits say: "The database still takes 2 seconds
to give up. A second circuit breaker, like the cache's, would turn those 2-second waits into
instant `503`s." Build it.

**Predict first.** Postgres is stopped and 20 people try to open uncached links. Right now each
one waits about 2 seconds. With a breaker, how long will the first one wait, and how long the
other 19? Write both. Which of the five store calls would you protect?

**What to do.** Open [`your-turn/t8_db_breaker.py`](your-turn/t8_db_breaker.py). The class
`BreakerStore` wraps a store and sends every call through `_guard`, which is empty. Build it from
the three states written in the file's header. Run the tests after every small step.

**Check yourself.**

```bash
uv run pytest labs/lab-1-url-shortener/your-turn -k t8
```

Five tests, all green. The second test fails the first call for real and then expects 20 more to
fail in well under a tenth of a second without touching the database again.

**Optional last step: try it on the real stack.** This is the only step that edits the running
system, so work on a branch (`git switch -c my-breaker`). Copy your finished file into
`labs/lab-1-url-shortener/system/shortener/src/shortener/`, wrap the store that `build_store` in
[wiring.py](system/shortener/src/shortener/wiring.py) returns, rebuild, then stop Postgres and
send two quick batches of requests for links that do not exist (use a Git Bash, macOS or Linux
shell; each of the three replicas has its own breaker):

```bash
docker compose -f labs/lab-1-url-shortener/docker-compose.yml up -d --build
docker compose -f labs/lab-1-url-shortener/docker-compose.yml stop postgres
for i in 1 2 3; do curl -s -o /dev/null -w "$i: %{http_code} in %{time_total}s\n" http://127.0.0.1:8080/NoSuch$i & done; wait
for i in 4 5 6 7 8 9; do curl -s -o /dev/null -w "$i: %{http_code} in %{time_total}s\n" http://127.0.0.1:8080/NoSuch$i & done; wait
docker compose -f labs/lab-1-url-shortener/docker-compose.yml start postgres
```

Write down what you expect for the first batch and the second before you run it. Without the
breaker every line takes about 2 seconds. A request that arrives just as a cooldown ends is the
test call and pays the full wait, so one or two slow lines in the second batch are normal.
Undo it with `git restore labs/lab-1-url-shortener/system`, delete the file you copied, and
rebuild.

**Stuck?** There are three things to remember between calls: whether the breaker is open, when it
opened, and whether a test call is already out.

### T9 A breaker that sends one scout

**Goal.** Build a missing piece. Part 3 measured a 252.7 ms p99 with Redis down and explained it:
"A breaker that lets *one* request test the water, not all of them, would fix that." Build that.

**Predict first.** Redis is down, the cooldown has just ended, and 20 requests arrive at the same
moment. With the cache as it is now, how many of them will go and wait on Redis? How many should?

**What to do.** [`your-turn/t9_half_open_cache.py`](your-turn/t9_half_open_cache.py) holds a copy
of the real cache with its breaker. Change it so that, once the cooldown ends, exactly one request
tests Redis while the rest keep skipping it. If the test works, everybody goes back to Redis. If
it fails, the breaker opens again. Read all five tests first: they say exactly what must hold,
including for `set` and `ping`.

**Check yourself.**

```bash
uv run pytest labs/lab-1-url-shortener/your-turn -k t9
```

Five tests, all green, the first one counting how many calls reached Redis out of twenty.

**Stuck?** The tricky part is not the "one scout" itself, it is making sure the scout is released
when it fails, when it succeeds, and when something unexpected goes wrong.

---

## When you are done

You have measured a cache, a queue and a worker, found two bugs and built two circuit breakers.
Compare your solutions with the files in [solutions/](solutions). Good next steps: run
`scenario.py run full_design` and see which row you could now explain without looking; or pick a
check that fails on purpose (`click_loss_redis_down`) and design a fix.
