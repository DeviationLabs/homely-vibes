// Array of Gmail Labels that are to be purged?
var GMAIL_LABELS = ["Kitchen", 
                    "MainEntrance",
                    "FrontYard",
                    "BackYard",
                    "BackYard_Stairs",
                    "Garage"];    

// Purge messages automatically after how many days?
var PURGE_AFTER = "30d";


/*
  For details, refer http://labnol.org/?p=27605

  T U T O R I A L
  - - - - - - - - 
  Step 1. Update the values of fields GMAIL_LABEL and PURGE_AFTER above.  
  Step 2. Go to Run -> Initialize and authorize the script.  
  Step 3. Go to Run -> Install to install the script.
  
  You can now exit this window and any email messages in Gmail folder will automatically 
  get purged after 'n' days. The script will run by itself everyday at 01:00 hours.
  
  Also, you may go to Run -> Uninstall to stop the purging script anytime.
*/


function Intialize() {
  return;
}

function Install() {
  ScriptApp.newTrigger("purgeGmail")
           .timeBased().everyDays(1).create();
}

function Uninstall() {
  var triggers = ScriptApp.getScriptTriggers();
  for (var i=0; i<triggers.length; i++) {
    ScriptApp.deleteTrigger(triggers[i]);
  }
}

function purgeGmail() {
  var MAX_ONCE = 100;   // Seems to be limit on # of child threads.. .
  
  // Cleanup scheduling debris ... 
  try {
    Uninstall();
    Install();
  } catch (e) {
    Install();
  }
  
  var search = "(label:" + GMAIL_LABELS.join(' OR label:') + ") older_than:" + PURGE_AFTER;
  Logger.log(search);
  
  try {
    var threads = GmailApp.search(search, 0, MAX_ONCE);
    
    if (threads.length == MAX_ONCE) {
      Logger.log('Rerunning on next ' + MAX_ONCE + '...')
      ScriptApp.newTrigger("purgeGmail")
               .timeBased()
               .at(new Date((new Date()).getTime() + 1000*60*1))
               .create();
    }
    
    for (var i=0; i<threads.length; i++) {
      var messages = GmailApp.getMessagesForThread(threads[i]);
      for (var j=0; j<messages.length; j++) {       
        Logger.log(messages[j].getDate() + "  " + messages[j].getSubject())
        messages[j].moveToTrash();
      }
    }
  } catch (e) {}
}

