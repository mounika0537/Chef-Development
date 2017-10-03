package 'httpd'

service 'httpd' do
 action [:enable, :start]
end

file '/Library/WebServer/Documents/index.html.en' do
 content '<html>
 <body>
 <h1> Hello Challa </h1>
 </body>
 </html>'
end

