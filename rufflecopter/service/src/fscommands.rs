use ruffle_core::external::FsCommandProvider;
use tokio::sync::mpsc::Sender;

pub struct MyFSCommandProvider {
    event_tx: Sender<String>
}

impl MyFSCommandProvider {
    pub fn new(tx: Sender<String>) -> MyFSCommandProvider {
        MyFSCommandProvider { event_tx: tx }
    }
}

impl FsCommandProvider for MyFSCommandProvider {
    fn on_fs_command(&self, command: &str, _args: &str) -> bool {
        match command {
            "quit" => {
                let _ = self.event_tx.try_send("quit".to_string());
            }
            "sleep" => {
                let _ = self.event_tx.try_send("sleep".to_string());
            }
            _ => return false,
        };
        true
    }
}