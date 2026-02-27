# Test Data Set

## Files
- `01_customers.csv`: customer master (one unmatched customer on orders side exists intentionally)
- `02_orders.csv`: orders (includes `C005` which does not exist in customers)
- `03_payments.csv`: payments (includes `O9999` unmatched)
- `04_events_for_asof.csv`: left table for asof join (`event_time`)
- `05_price_timeline_for_asof.csv`: right table for asof join (`rate_time`, `cust_id`)
- `06_union_sales_jan.csv`: base table for union
- `07_union_sales_feb_variant.csv`: union target with different column names (`cust_id/date/amt/sales_channel`)
- `08_composite_left.csv`, `09_composite_right.csv`: composite-key join test pair

## Suggested UI checks
1. Multi-step join:
   - base=`02_orders.csv`
   - step1: left join `01_customers.csv` on `customer_id`
   - step2: left join `03_payments.csv` on `order_id`
   - confirm unmatched extraction for `C005` and `O9999`
2. asof join:
   - base=`04_events_for_asof.csv`
   - step1: `join` + `asof`
   - left key=`event_time`, right key=`rate_time`
   - left by=`customer_id`, right by=`cust_id`
   - direction=`backward`, tolerance=`10min`
3. union:
   - base=`06_union_sales_jan.csv`
   - step1: `union` with `07_union_sales_feb_variant.csv`
   - confirm auto proposals map `cust_id->customer_id`, `date->order_date`, `amt->amount`
   - review `sales_channel` and `memo` as new columns or remap manually
