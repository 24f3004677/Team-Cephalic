


select * from "user" as u where u.role='admin'
select n.name as Node_name,* from sensor_data as sd , node as n  where (sd.node_id=n.id)
select * from "user" as u
select * from (select * from mine) order by id asc
select * from node
select distinct mine_id,from_node_id,to_node_id from mine_nodes as m_n join node_links as nl on m_n.mine_id=nl.from_node_id where m_n.mine_id=2 order by nl.to_node_id ASC  

select distinct mine_id,from_node_id,to_node_id from mine_nodes as m_n join node_links as nl on m_n.mine_id=nl.from_node_id order by nl.to_node_id ASC  

select * from alert

select * from user_mines
select * from node_links
select * from user_mines


-- for deleting the entier database 
-- this is mainly for the changing the database model like adding/deleting new column
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;