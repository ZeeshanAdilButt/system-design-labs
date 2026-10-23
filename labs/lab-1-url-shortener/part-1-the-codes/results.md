# Part 1 · The codes: results

## When does the first collision happen?

| code length | codes possible | links until first repeat (median) | the formula says |
|---|---|---|---|
| 4 | 14,776,336 | 4,624 | 4,818 |
| 5 | 916,132,832 | 37,205 | 37,935 |
| 6 | 56,800,235,584 | 274,789 | 298,700 |

## Retries needed while creating links (6-character codes)

| links created | random codes: retries | counter + shuffle: retries |
|---|---|---|
| 10,000 | 0 | 0 |
| 100,000 | 0 | 0 |
| 300,000 | 1 | 0 |
| 1,000,000 | 3 | 0 |

## Example codes

| counter value | code | decodes back to |
|---|---|---|
| 0 | tUwWP2 | 0 |
| 1 | IdZ23b | 1 |
| 2 | E4sFdy | 2 |
| 3 | fZzCX3 | 3 |
| 4 | f9wFUK | 4 |

## Trips to the shared counter to create 100,000 links

| how ids are handed out | trips to the database |
|---|---|
| one id per trip | 100,000 |
| a block of 1000 per trip | 100 |

## How long do 6 characters last?

| new links per second | years until the 6-character codes run out |
|---|---|
| 10 | 180 |
| 100 | 18 |
| 1000 | 2 |

