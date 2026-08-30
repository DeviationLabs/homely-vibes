<?php
exec("PYTHONPATH=lib HOME=. ./NodeCheck/check_nodes.py --reboot --always_email");
header('Location: /reboot_applied.html');
?>
