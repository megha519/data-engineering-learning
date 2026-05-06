pivoting


  
  update orders
  set ordered_date = 
case when order_id = 1 then '2026-12-01' 
  when order_id = 2 then '2026-12-02'
  when order_id = 3 then '2026-12-03'
  when order_id = 4 then '2025-12-01' 
  when order_id = 5 then '2025-12-02'
end
