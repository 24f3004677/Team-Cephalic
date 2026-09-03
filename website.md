# Website purpose
- to visualise the sensor data from the coal mine
- show status of each node 
- option for creating new node as the coal mine extends
- to send alert to a specific nodes or a group of nodes if there is any emergency --> manual + automatic
- main purpose is to get data from the sensors placed in the coal mine through esp32 board then send it to data processing unit(not the part of website), the processing unit(a custom ml model) will send its analysis and it will be reflected in the website
- eg after getting data from the sensors it was sent to the processing unit then processing unit sends the analysis like [[3,1,1],[2,4,0],[1,2,2]] syntax:[[mine_id,node_id,status]]status:0->under control,1->need attention,2->danger
- each mine can have many nodes ; two mines can have nodes in common;each mine can have many engineers and supervisers
# roles
## admin --> super user
  - can do all the things 
    - creating new node , sending alert , blacklist/unblacklist/remove engineers & superviders
    - create new engineer and superviser
## Engineeres/ supervisers
  - can only login after the admin creates their login credential 
  - can creating new node , sending alert 
  - can see if any their respective mine's gets any error/distress signal from nodes
# website structure

### Web_pages
  - home page(all)
    - Dashboard of number of mines,nodes, engineers/superviser, number of workers inside mines
    - a clickable card for each mine with some info about the mine(mine_name,location,Engineer/superviser,number of workers,status)
    - data of each node is send to processing unit(ml model) which will then provide its analysis and upon that the status of the node and mine will change and the data is sent continuously after 10s
    - if the data sent by the processing unit is danger then the it will instantly send a signal to that node and then the node will start alarming
    - when click on the card then it will show the cards of nodes under that mine, its sensor data and a button for analysis,emergency alarm
    - upon clicking the analysis button the backend will show charts each sensor's data over past data
    - upon clicking the emergency alarm it will send a signal to that node and then the node will start alarming.
  - navbar logo,login/logout,office
  - the office tab will take to a page where admin will have option to create new engineer/superviser,node,mine,job_shift(which mine and its respective engineer , superviser, time shift(day,evening,night))
  - logs option where it will show card for each mine, on clicking on the card it will show which shift has which engineer and superviser
    