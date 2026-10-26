# Looker expressions function & Excel-equivalents reference

Full function and operator mapping between Looker expressions and Microsoft Excel formulas, split by execution context (`SQL pushdown` vs. `post-query in-memory`).

## Available in ALL Looker expressions (SQL pushdown & in-memory)

### Logical, comparison, and constants

| Looker expression | Equivalent Excel formula | Notes |
| :--- | :--- | :--- |
| `a = b`, `a != b`, `<`, `<=`, `>`, `>=` | `A2 = B2`, `A2 <> B2`, `<`, `<=`, `>`, `>=` | Looker uses `!=` (not `<>`). |
| `a AND b`, `a OR b`, `NOT a` | `AND(A2, B2)`, `OR(A2, B2)`, `NOT(A2)` | Infix in Looker; must be `UPPERCASE`. |
| `yes`, `no`, `null` | `TRUE`, `FALSE`, `""` / blank cell | Lowercase unquoted symbols in Looker. |
| `if(cond, if_yes, if_no)` | `IF(cond, if_true, if_false)` | |
| `case(when(c1, v1), when(c2, v2), else_v)` | `IFS(c1, v1, c2, v2, TRUE, else_v)` | Evaluates `when()` branches top-down. |
| `coalesce(v1, v2, ...)` | `IF(NOT(ISBLANK(A2)), A2, B2)` | First non-null argument. |
| `is_null(x)` | `ISBLANK(A2)` | Returns `yes` if `x` is `null`. |

### Mathematical (row-level)

| Looker expression | Equivalent Excel formula | Notes |
| :--- | :--- | :--- |
| `a + b`, `a - b`, `a * b`, `a / b` | `A2 + B2`, `A2 - B2`, `A2 * B2`, `A2 / B2` | Guard zero denominators with `if(b = 0, null, a / b)`. |
| `abs(x)` | `ABS(A2)` | Absolute value. |
| `ceiling(x)` / `floor(x)` | `CEILING.MATH(A2)` / `FLOOR.MATH(A2)` | Smallest integer `>= x` / largest integer `<= x`. |
| `round(x, num_decimals)` | `ROUND(A2, num_decimals)` | |
| `sqrt(x)` / `power(base, exp)` | `SQRT(A2)` / `POWER(A2, exp)` (`A2 ^ exp`) | `^` is not an operator in Looker. |
| `mod(x, divisor)` | `MOD(A2, divisor)` | Remainder of `x / divisor`. |
| `exp(x)` / `ln(x)` / `log(x)` | `EXP(A2)` / `LN(A2)` / `LOG10(A2)` | `e^x`, natural log, base-10 log. |
| `rand()` | `RAND()` | Uniform random float in `[0, 1)`. |

### String

| Looker expression | Equivalent Excel formula | Notes |
| :--- | :--- | :--- |
| `concat(s1, s2, ...)` | `CONCAT(A2, B2, ...)` (`A2 & B2`) | `+` cannot join strings in Looker. |
| `contains(str, search_str)` | `ISNUMBER(FIND(search_str, A2))` | **Case-sensitive**; argument order is `(haystack, needle)` (reversed vs. Excel `FIND`). |
| `position(str, search_str)` | `IFERROR(FIND(search_str, A2), 0)` | 1-based start index (`0` if absent); `(haystack, needle)` order. |
| `length(str)` | `LEN(A2)` | Character count. |
| `lower(str)` / `upper(str)` | `LOWER(A2)` / `UPPER(A2)` | |
| `replace(str, old_str, new_str)` | `SUBSTITUTE(A2, old_str, new_str)` | Replaces **all** occurrences by text match (like Excel `SUBSTITUTE`, not positional `REPLACE`). |
| `substring(str, start_pos, len)` | `MID(A2, start_pos, len)` | `start_pos` is 1-based. |

### Date and time

| Looker expression | Equivalent Excel formula | Notes |
| :--- | :--- | :--- |
| `now()` | `NOW()` | Current timestamp. |
| `date(y, m, d)` | `DATE(y, m, d)` | Returns `null` if invalid date. |
| `date_time(y, m, d, h, min, s)` | `DATE(y, m, d) + TIME(h, min, s)` | |
| `add_days(n, d)` | `A2 + n` | **`n` is first argument** (`add_days(number, date)`). |
| `add_months(n, d)` / `add_years(n, d)` | `EDATE(A2, n)` / `EDATE(A2, n * 12)` | **`n` is first argument**. |
| `add_hours(n, d)` / `add_minutes(n, d)` / `add_seconds(n, d)` | `A2 + (n / 24)` / `A2 + (n / 1440)` / `A2 + (n / 86400)` | **`n` is first argument**. |
| `diff_days(start_d, end_d)` | `DAYS(end_d, start_d)` (`end_d - start_d`) | **`start_d` first, `end_d` second** (reversed vs. Excel `DAYS`). |
| `diff_months(start_d, end_d)` / `diff_years(start_d, end_d)` | `DATEDIF(start_d, end_d, "M")` / `DATEDIF(start_d, end_d, "Y")` | Signed difference (`end - start`). |
| `diff_hours` / `diff_minutes` / `diff_seconds(start_d, end_d)` | `(end_d - start_d) * 24` / `* 1440` / `* 86400` | Signed difference (`end - start`). |
| `extract_years(d)` / `extract_months(d)` / `extract_days(d)` | `YEAR(A2)` / `MONTH(A2)` / `DAY(A2)` | |
| `extract_hours(d)` / `extract_minutes(d)` / `extract_seconds(d)` | `HOUR(A2)` / `MINUTE(A2)` / `SECOND(A2)` | |
| `trunc_years(d)` / `trunc_months(d)` / `trunc_days(d)` | `DATE(YEAR(A2), 1, 1)` / `DATE(YEAR(A2), MONTH(A2), 1)` / `INT(A2)` | Truncates to start of period. |
| `trunc_hours(d)` / `trunc_minutes(d)` | `INT(A2) + TIME(HOUR(A2), 0, 0)` / `INT(A2) + TIME(HOUR(A2), MINUTE(A2), 0)` | |

---

## Custom Filters, Custom Fields & NDT `expression_custom_filter:` ONLY (SQL pushdown)

| Looker expression | Equivalent Excel formula | Notes |
| :--- | :--- | :--- |
| ``matches_filter(${view.field}, `filter_expr`)`` | `COUNTIFS(A2, criteria) > 0` | Evaluates a [looker-filters](../../looker-filters/SKILL.md) string (enclosed in backticks) to `yes`/`no`. Invalid in Table Calculations and Data Tests. |

---

## Table Calculations & LookML Data Test `assert:` ONLY (post-query in-memory)

### Totals, positional (row), and pivot (column) functions

| Looker expression | Equivalent Excel formula | Notes |
| :--- | :--- | :--- |
| `${field:total}` / `${field:row_total}` | `SUM(B$2:B$100)` / `SUM($B2:$M2)` | Requires column/row totals enabled (`"total": True` / `"row_total": "right"`). |
| `row()` | `ROW() - ROW($A$1)` | 1-based row index in the result table. |
| `offset(col, row_offset)` | `OFFSET(B2, row_offset, 0)` | Relative row (`-1` = row above, `1` = row below). Disables sorting on calc. |
| `offset_list(col, row_offset, len)` | `OFFSET(B2, row_offset, 0, len, 1)` | List of `len` values starting at `row() + row_offset`. |
| `index(col, n)` | `INDEX(B$2:B$100, n)` | Value at 1-based row `n` (or `n`-th item when `col` is a list). |
| `match(val, col)` | `MATCH(val, A$2:A$100, 0)` | 1-based row of **first** exact match in `col` (or index within each row's list). |
| `lookup(val, lookup_col, result_col)` | `XLOOKUP(val, A$2:A$100, B$2:B$100)` | Equivalent to `index(result_col, match(val, lookup_col))`. |
| `list(v1, v2, ...)` | `HSTACK(v1, v2, ...)` (`{v1, v2, ...}`) | Builds a list value for per-row list aggregations. |
| `pivot_column()` | `COLUMN() - COLUMN($B2) + 1` | 1-based index of the current pivot column. |
| `pivot_index(expr, p)` | `INDEX($B2:$M2, 1, p)` | Evaluates `expr` in 1-based pivot column `p`. |
| `pivot_offset(expr, col_offset)` | `OFFSET(B2, 0, col_offset)` | Relative pivot column (`-1` = pivot column to left). |
| `pivot_offset_list(expr, col_offset, len)` | `OFFSET(B2, 0, col_offset, 1, len)` | List of `len` pivot values across the row. |
| `pivot_row(expr)` | `$B2:$M2` | All pivoted values of `expr` for the current row as a list. |
| `pivot_where(select_expr, expr)` | `XLOOKUP(TRUE, cond_row, $B2:$M2)` | Value of `expr` in the unique pivot column where `select_expr` is `yes` (`null` if not unique). |

### Column / list aggregates, rankings, conversions, and statistical functions

*(When passed a column `${view.field}`, these reduce the entire displayed column; when passed a list per row like `offset_list(...)` or `pivot_row(...)`, they reduce each row's list.)*

| Looker expression | Equivalent Excel formula | Notes |
| :--- | :--- | :--- |
| `sum(x)` / `product(x)` | `SUM(B$2:B$100)` / `PRODUCT(B$2:B$100)` | |
| `running_total(x)` / `running_product(x)` | `SUM(B$2:B2)` / `PRODUCT(B$2:B2)` (`SCAN(...)`) | Cumulative down displayed rows. |
| `mean(x)` / `geomean(x)` | `AVERAGE(B$2:B$100)` / `GEOMEAN(B$2:B$100)` | Arithmetic / geometric mean (ignores `null`). |
| `median(x)` / `mode(x)` | `MEDIAN(B$2:B$100)` / `MODE.SNGL(B$2:B$100)` | |
| `min(x)` / `max(x)` | `MIN(B$2:B$100)` / `MAX(B$2:B$100)` | |
| `large(x, k)` / `small(x, k)` | `LARGE(B$2:B$100, k)` / `SMALL(B$2:B$100, k)` | $k$-th largest / smallest value. |
| `count(x)` / `count_distinct(x)` | `COUNTA(B$2:B$100)` / `COUNTA(UNIQUE(B$2:B$100))` | Counts non-null values / distinct non-null values. |
| `rank(val, col)` / `rank_avg(val, col)` | `RANK.EQ(B2, B$2:B$100)` / `RANK.AVG(B2, B$2:B$100)` | Competition rank / average tie rank. |
| `percent_rank(col, val)` | `PERCENTRANK.INC(B$2:B$100, B2)` | `[0, 1]` inclusive; note `(col, val)` order matches Excel. |
| `percentile(col, p)` | `PERCENTILE.INC(B$2:B$100, p)` | `p` must be in `[0, 1]`. |
| `to_number(s)` / `to_string(x)` / `to_date(s)` | `VALUE(A2)` / `TEXT(A2, "@")` / `DATEVALUE(A2)` | Type conversions (`to_date` parses `YYYY[-MM[-DD[ hh[:mm[:ss]]]]]`). |
| `split(str, delimiter)` | `TEXTSPLIT(A2, delimiter)` | Splits string into a list. |
| `stddev_pop(x)` / `stddev_samp(x)` | `STDEV.P(B$2:B$100)` / `STDEV.S(B$2:B$100)` | Population / sample standard deviation. |
| `var_pop(x)` / `var_samp(x)` | `VAR.P(B$2:B$100)` / `VAR.S(B$2:B$100)` | Population / sample variance. |
| `correl(y, x)` / `covar_pop(y, x)` / `covar_samp(y, x)` | `CORREL(Y, X)` / `COVARIANCE.P(Y, X)` / `COVARIANCE.S(Y, X)` | |
| `slope(y, x)` / `intercept(y, x)` / `skew(x)` / `kurtosis(x)` | `SLOPE(Y, X)` / `INTERCEPT(Y, X)` / `SKEW(X)` / `KURT(X)` | Linear regression & higher moments. |
| `pi()`, `sin`/`cos`/`tan`, `acos`/`asin`/`atan`, `degrees`/`radians` | `PI()`, `SIN`/`COS`/`TAN`, `ACOS`/`ASIN`/`ATAN`, `DEGREES`/`RADIANS` | Standard trigonometry. |
| `fact(n)` / `combin(n, k)` / `multinomial(v1, v2, ...)` | `FACT(n)` / `COMBIN(n, k)` / `MULTINOMIAL(v1, v2, ...)` | Combinatorics. |
| `norm_dist` / `norm_inv` / `norm_s_dist` / `norm_s_inv` | `NORM.DIST` / `NORM.INV` / `NORM.S.DIST` / `NORM.S.INV` | Normal & standard normal distributions (`cumulative` takes `yes`/`no`). |
| `t_dist` / `t_inv` / `t_test` / `z_test` / `confidence_norm` / `confidence_t` | `T.DIST` / `T.INV` / `T.TEST` / `Z.TEST` / `CONFIDENCE.NORM` / `CONFIDENCE.T` | Hypothesis tests & confidence half-widths. |
| `chisq_dist` / `chisq_inv` / `chisq_test` / `f_dist` / `f_inv` | `CHISQ.DIST` / `CHISQ.INV` / `CHISQ.TEST` / `F.DIST` / `F.INV` | $\chi^2$ and $F$ distributions/tests. |
| `binom_dist` / `binom_inv` / `negbinom_dist` / `hypgeom_dist` / `poisson_dist` / `expon_dist` / `gamma_dist` / `gamma_inv` / `beta_dist` / `beta_inv` / `weibull_dist` | `BINOM.DIST` / `BINOM.INV` / `NEGBINOM.DIST` / `HYPGEOM.DIST` / `POISSON.DIST` / `EXPON.DIST` / `GAMMA.DIST` / `GAMMA.INV` / `BETA.DIST` / `BETA.INV` / `WEIBULL.DIST` | Discrete & continuous probability distributions. |
