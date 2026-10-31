-- Prints every row of every table: run it locally, never commit its output (the source has no licence).
-- Full dump of every table, in rowid order, with typeof() per column.
-- name: dump_access_log
select rowid, session, user_id, action, stamp from access_log order by rowid;
-- name: types_access_log
select typeof(session) as session, typeof(user_id) as user_id, typeof(action) as action, typeof(stamp) as stamp, count(*) n from access_log group by typeof(session), typeof(user_id), typeof(action), typeof(stamp);
-- name: dump_action_log
select rowid, session, user_id, action, category, products, amount, stamp from action_log order by rowid;
-- name: types_action_log
select typeof(session) as session, typeof(user_id) as user_id, typeof(action) as action, typeof(category) as category, typeof(products) as products, typeof(amount) as amount, typeof(stamp) as stamp, count(*) n from action_log group by typeof(session), typeof(user_id), typeof(action), typeof(category), typeof(products), typeof(amount), typeof(stamp);
-- name: dump_action_log_with_ip
select rowid, session, user_id, action, ip, stamp from action_log_with_ip order by rowid;
-- name: types_action_log_with_ip
select typeof(session) as session, typeof(user_id) as user_id, typeof(action) as action, typeof(ip) as ip, typeof(stamp) as stamp, count(*) n from action_log_with_ip group by typeof(session), typeof(user_id), typeof(action), typeof(ip), typeof(stamp);
-- name: dump_action_log_with_noise
select rowid, stamp, session, action, products, url, ip, user_agent from action_log_with_noise order by rowid;
-- name: types_action_log_with_noise
select typeof(stamp) as stamp, typeof(session) as session, typeof(action) as action, typeof(products) as products, typeof(url) as url, typeof(ip) as ip, typeof(user_agent) as user_agent, count(*) n from action_log_with_noise group by typeof(stamp), typeof(session), typeof(action), typeof(products), typeof(url), typeof(ip), typeof(user_agent);
-- name: dump_activity_log
select rowid, stamp, session, action, option, path, search_type from activity_log order by rowid;
-- name: types_activity_log
select typeof(stamp) as stamp, typeof(session) as session, typeof(action) as action, typeof(option) as option, typeof(path) as path, typeof(search_type) as search_type, count(*) n from activity_log group by typeof(stamp), typeof(session), typeof(action), typeof(option), typeof(path), typeof(search_type);
-- name: dump_app1_mst_users
select rowid, user_id, name, email from app1_mst_users order by rowid;
-- name: types_app1_mst_users
select typeof(user_id) as user_id, typeof(name) as name, typeof(email) as email, count(*) n from app1_mst_users group by typeof(user_id), typeof(name), typeof(email);
-- name: dump_app2_mst_users
select rowid, user_id, name, phone from app2_mst_users order by rowid;
-- name: types_app2_mst_users
select typeof(user_id) as user_id, typeof(name) as name, typeof(phone) as phone, count(*) n from app2_mst_users group by typeof(user_id), typeof(name), typeof(phone);
-- name: dump_dup_action_log
select rowid, stamp, session, user_id, action, products from dup_action_log order by rowid;
-- name: types_dup_action_log
select typeof(stamp) as stamp, typeof(session) as session, typeof(user_id) as user_id, typeof(action) as action, typeof(products) as products, count(*) n from dup_action_log group by typeof(stamp), typeof(session), typeof(user_id), typeof(action), typeof(products);
-- name: dump_form_error_log
select rowid, stamp, session, form, field, error_type, value from form_error_log order by rowid;
-- name: types_form_error_log
select typeof(stamp) as stamp, typeof(session) as session, typeof(form) as form, typeof(field) as field, typeof(error_type) as error_type, typeof(value) as value, count(*) n from form_error_log group by typeof(stamp), typeof(session), typeof(form), typeof(field), typeof(error_type), typeof(value);
-- name: dump_form_log
select rowid, stamp, session, action, path, status from form_log order by rowid;
-- name: types_form_log
select typeof(stamp) as stamp, typeof(session) as session, typeof(action) as action, typeof(path) as path, typeof(status) as status, count(*) n from form_log group by typeof(stamp), typeof(session), typeof(action), typeof(path), typeof(status);
-- name: dump_invalid_action_log
select rowid, stamp, session, user_id, action, category, products, amount from invalid_action_log order by rowid;
-- name: types_invalid_action_log
select typeof(stamp) as stamp, typeof(session) as session, typeof(user_id) as user_id, typeof(action) as action, typeof(category) as category, typeof(products) as products, typeof(amount) as amount, count(*) n from invalid_action_log group by typeof(stamp), typeof(session), typeof(user_id), typeof(action), typeof(category), typeof(products), typeof(amount);
-- name: dump_mst_categories
select rowid, id, name, stamp from mst_categories order by rowid;
-- name: types_mst_categories
select typeof(id) as id, typeof(name) as name, typeof(stamp) as stamp, count(*) n from mst_categories group by typeof(id), typeof(name), typeof(stamp);
-- name: dump_mst_products_20161201
select rowid, product_id, name, price, updated_at from mst_products_20161201 order by rowid;
-- name: types_mst_products_20161201
select typeof(product_id) as product_id, typeof(name) as name, typeof(price) as price, typeof(updated_at) as updated_at, count(*) n from mst_products_20161201 group by typeof(product_id), typeof(name), typeof(price), typeof(updated_at);
-- name: dump_mst_products_20170101
select rowid, product_id, name, price, updated_at from mst_products_20170101 order by rowid;
-- name: types_mst_products_20170101
select typeof(product_id) as product_id, typeof(name) as name, typeof(price) as price, typeof(updated_at) as updated_at, count(*) n from mst_products_20170101 group by typeof(product_id), typeof(name), typeof(price), typeof(updated_at);
-- name: dump_mst_users
select rowid, user_id, sex, birth_date, register_date, register_device, withdraw_date from mst_users order by rowid;
-- name: types_mst_users
select typeof(user_id) as user_id, typeof(sex) as sex, typeof(birth_date) as birth_date, typeof(register_date) as register_date, typeof(register_device) as register_device, typeof(withdraw_date) as withdraw_date, count(*) n from mst_users group by typeof(user_id), typeof(sex), typeof(birth_date), typeof(register_date), typeof(register_device), typeof(withdraw_date);
-- name: dump_mst_users_with_card_number
select rowid, user_id, card_number from mst_users_with_card_number order by rowid;
-- name: types_mst_users_with_card_number
select typeof(user_id) as user_id, typeof(card_number) as card_number, count(*) n from mst_users_with_card_number group by typeof(user_id), typeof(card_number);
-- name: dump_product_sales
select rowid, category_name, product_id, sales from product_sales order by rowid;
-- name: types_product_sales
select typeof(category_name) as category_name, typeof(product_id) as product_id, typeof(sales) as sales, count(*) n from product_sales group by typeof(category_name), typeof(product_id), typeof(sales);
-- name: dump_purchase_log
select rowid, purchase_id, user_id, amount, stamp from purchase_log order by rowid;
-- name: types_purchase_log
select typeof(purchase_id) as purchase_id, typeof(user_id) as user_id, typeof(amount) as amount, typeof(stamp) as stamp, count(*) n from purchase_log group by typeof(purchase_id), typeof(user_id), typeof(amount), typeof(stamp);
-- name: dump_read_log
select rowid, stamp, session, action, url from read_log order by rowid;
-- name: types_read_log
select typeof(stamp) as stamp, typeof(session) as session, typeof(action) as action, typeof(url) as url, count(*) n from read_log group by typeof(stamp), typeof(session), typeof(action), typeof(url);
