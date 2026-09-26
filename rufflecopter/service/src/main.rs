use std::fs::File;
use std::io::Read;
use ruffle_core::tag_utils::SwfMovie;
use std::any::Any;
use tokio::sync::mpsc;
use tokio::task::LocalSet;
use tokio::time::{sleep, Duration};
use ruffle_core::{FloatDuration, PlayerBuilder};
use ruffle_core::backend::navigator::OwnedFuture;
use ruffle_core::loader::Error;

mod navigator;
use navigator::Mynavigator;

mod fscommands;
use fscommands::MyFSCommandProvider;

fn main() -> anyhow::Result<()> {
    unsafe { libc::signal(libc::SIGCHLD, libc::SIG_IGN); }

    let path = "server.swf";
    let url = "file://".to_string() + path;

    tracing_subscriber::fmt::init();
    
    let mut file = File::open(path)?;
    let mut buffer = Vec::new();
    file.read_to_end(&mut buffer)?;
    let movie: SwfMovie = SwfMovie::from_data(&buffer, url.to_string(), None, None).unwrap();


    let (event_tx, mut event_rx) = mpsc::channel(10);
    let (tick_tx, mut tick_rx) = mpsc::channel::<u32>(1);
    let navigator = Mynavigator::new(tick_tx.clone());
    let player =
        PlayerBuilder::new()
        .with_movie(movie)
        .with_navigator(navigator)
        .with_fs_commands(Box::new(MyFSCommandProvider::new(event_tx)))
        .build();

    let _ = tick_tx.try_send(200);

    {
        let mut player = player.lock().unwrap();
        player.suspend_after_next_frame();
        player.tick(FloatDuration::from_millis(1000.0));
    }

    let runtime = Box::new(tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap());

    runtime.block_on(async move {
        let local_set = LocalSet::new();

        local_set.spawn_local(async move {
            loop {
                let num_ticks = match tick_rx.recv().await{
                    Some(ticks) => ticks,
                    None => { break; }
                };

                for _ in 1..num_ticks {
                    if let Ok(msg) = event_rx.try_recv() {
                        match msg.as_str()  {
                            "quit" => { sleep(Duration::from_millis(100)).await; return; },
                            "sleep" => { println!("sleeping"); break; },
                            _ => { }
                        }
                    }
                    let mut futures = Vec::<OwnedFuture<(), Error>>::new();
                    {
                        let mut player = player.lock().unwrap();
                        let navigator: &mut Mynavigator = <dyn Any>::downcast_mut::<Mynavigator>(player.navigator_mut()).expect("Wrong navigator");
                        navigator.update();

                        while let Some(f) = navigator.futures.pop() {
                            futures.push(f);
                        }

                        player.suspend_after_next_frame();
                        player.tick(FloatDuration::from_millis(1000.0));
                    }

                    while let Some(f) = futures.pop() {
                        let _ = f.await;
                    }
                }
            }
        });

        local_set.await;
    });
    Ok(())
}
