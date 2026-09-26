use std::path::Path;
use std::time::Duration;
use std::fs;
use std::borrow::Cow;
use std::io::ErrorKind;
use std::net::{TcpStream, SocketAddr};
use url::{ParseError, Url};
use async_channel::{Receiver, Sender, TryRecvError};
use tokio;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::sync::mpsc;
use ruffle_core::socket::{ConnectionState, SocketAction, SocketHandle};
use ruffle_core::backend::navigator::{ErrorResponse, SuccessResponse, NavigatorBackend, NavigationMethod, Request, OwnedFuture};
use ruffle_core::swf::Encoding;
use ruffle_core::loader::Error::{self, IoError, FetchError};
use ruffle_core::indexmap::IndexMap;
use bytes::Bytes;


struct AVMConnection {
    ruffle_sender: async_channel::Sender<SocketAction>,
    ruffle_receiver: async_channel::Receiver<Vec<u8>>,
    ruffle_handle: SocketHandle
}

enum ConnectionRequest {
    ExitstingStream(TcpStream, SocketAddr, AVMConnection),
    Address(String, u16, AVMConnection)
}


pub struct Mynavigator {
    connection_requests: Vec<ConnectionRequest>,
    pub futures: Vec<OwnedFuture<(), Error>>,
    tick_tx: mpsc::Sender<u32>,
}

impl Mynavigator {
    pub fn new(tick_tx: mpsc::Sender<u32>) -> Mynavigator
    {
        Mynavigator{ connection_requests: Vec::new(), futures: Vec::new(), tick_tx }
    }

    pub fn update(&mut self) {
        while self.connection_requests.len() > 0 {
            let req = self.connection_requests.pop().unwrap();
            Self::spawn_connect_task(self.tick_tx.clone(), req);
        }
    }

    async fn send_action(sender: &Sender<SocketAction>, action: SocketAction) -> bool {
        sender
        .send(action)
        .await
        .inspect_err(|err| tracing::warn!("Failed to send SocketAction: {}", err))
        .is_ok()
    }

    fn spawn_connect_task(tick_tx: mpsc::Sender<u32>, req: ConnectionRequest) {
        tokio::spawn(async move {
            let (stream, avm) = match req {
                ConnectionRequest::ExitstingStream(stream, _addr, avm) => {
                    let action = SocketAction::Connect(avm.ruffle_handle, ConnectionState::Connected);
                    if !Self::send_action(&avm.ruffle_sender, action).await {
                        return;
                    }
                    (stream, avm)
                },
                ConnectionRequest::Address(host, port, avm) => {
                    let stream = std::net::TcpStream::connect((host, port)).unwrap();
                    let action = SocketAction::Connect(avm.ruffle_handle, ConnectionState::Connected);
                    if !Self::send_action(&avm.ruffle_sender, action).await {
                        return;
                    }
                    (stream, avm)
                }
            };
            Self::spawn_stream_task(tick_tx.clone(), stream, avm);
        });
    }

    fn spawn_stream_task(tick_tx: mpsc::Sender<u32>, std_stream: std::net::TcpStream, avm_connection: AVMConnection) {
        tokio::spawn(async move {
            let _ = std_stream.set_nonblocking(true).unwrap();
            let mut stream = tokio::net::TcpStream::from_std(std_stream).unwrap();

            let sender2 = avm_connection.ruffle_sender.clone();
            let (mut read, mut write) = stream.split();

            let read = async move {
                loop {
                    let mut buffer = [0; 4096];

                    match read.read(&mut buffer).await {
                        Err(e) if e.kind() == ErrorKind::TimedOut => { } // try again later.
                        Err(_) | Ok(0) => {
                            let _ = Self::send_action(&avm_connection.ruffle_sender, SocketAction::Close(avm_connection.ruffle_handle)).await;
                            let _ = tick_tx.try_send(200);
                            break;
                        }
                        Ok(read) => {
                            let buffer = buffer.into_iter().take(read).collect::<Vec<_>>();

                            let action = SocketAction::Data(avm_connection.ruffle_handle, buffer);
                            let _ = tick_tx.try_send(200);
                            if !Self::send_action(&avm_connection.ruffle_sender, action).await {
                                return;
                            }
                        }
                    };
                }
            };

            let write = async move {
                let mut pending_write = vec![];

                loop {
                    let close_connection = loop {
                        match avm_connection.ruffle_receiver.try_recv() {
                            Ok(val) => {
                                pending_write.extend(val);
                            }
                            Err(TryRecvError::Empty) => break false,
                            Err(TryRecvError::Closed) => {
                                //NOTE: Channel sender has been dropped.
                                //      This means we have to close the connection,
                                //      but not here, as we might have a pending write.
                                break true;
                            }
                        }
                    };

                    if !pending_write.is_empty() {
                        match write.write(&pending_write).await {
                            Err(e) if e.kind() == ErrorKind::TimedOut => {} // try again later.
                            Err(_) => {
                                let _ = Self::send_action(&sender2, SocketAction::Close(avm_connection.ruffle_handle)).await;
                                return;
                            }
                            Ok(written) => {
                                let _ = pending_write.drain(..written);
                            }
                        }
                    } else if close_connection {
                        return;
                    } else {
                        // Receiver is empty and there's no pending data,
                        // we may block here and wait for new data.
                        match avm_connection.ruffle_receiver.recv().await {
                            Ok(val) => {
                                pending_write.extend(val);
                            }
                            Err(_) => {
                                // Ignore the error here, it will be
                                // reported again in try_recv.
                            }
                        }
                    }
                }
            };

            tokio::select! {
            _ = read => {},
            _ = write => {},
            };

            println!("Closed");

            if let Err(e) = stream.shutdown().await {
                tracing::warn!("Failed to shutdown write half of TcpStream: {e}");
            }
        });
    }

}

impl NavigatorBackend for Mynavigator {
    fn navigate_to_url(
        &self,
        _url: &str,
        _target: &str,
        _vars_method: Option<(NavigationMethod, IndexMap<String, String>)>,
    ) {
        panic!("navigate_to_url not implemented");
    }

    fn fetch(&self, request: Request) -> OwnedFuture<Box<dyn SuccessResponse>, ErrorResponse> {
        struct MyResponse {
            url: String,
            status: u16,
            data: Vec<u8>,
        }
        impl SuccessResponse for MyResponse {
            fn url(&self)                      -> Cow<'_, str>                        { Cow::Borrowed(&self.url) }
            fn set_url(&mut self, url: String)                                        { self.url = url }
            fn body(self: Box<Self>)           -> OwnedFuture<Vec<u8>, Error>         { Box::pin(async move { Ok(self.data) }) }
            fn text_encoding(&self)            -> Option<&'static Encoding>           { None }
            fn status(&self)                   -> u16                                 { self.status }
            fn redirected(&self)               -> bool                                { false }
            fn next_chunk(&mut self)           -> OwnedFuture<Option<Vec<u8>>, Error> { Box::pin(async move { Ok(Some(Vec::new())) }) }
            fn expected_length(&self)          -> Result<Option<u64>, Error>          { Ok(Some(self.data.len().try_into().unwrap())) }
        }

        
        if let Ok(processed_url) = Url::parse(request.url()) {
            return Box::pin(async move {
                let client = reqwest::Client::new();
                let mut request_builder = match request.method() {
                    NavigationMethod::Get  => client.get (processed_url.clone()),
                    NavigationMethod::Post => client.post(processed_url.clone()),
                };

                if let Some(body) = request.body() {
                    request_builder = request_builder.body(body.0.clone());
                }
                for (name, val) in request.headers().iter() {
                    request_builder = request_builder.header(name, val);
                }
                let result = request_builder.send().await;

                match result {
                    Ok(response) => {
                        let success_response: Box<dyn SuccessResponse> = Box::new(MyResponse {
                            url: processed_url.to_string(),
                            status: response.status().as_u16(),
                            data: response.bytes().await.unwrap_or(Bytes::new()).into(),
                        });
                        Ok(success_response)
                    },
                    Err(e) => {
                        Err(ErrorResponse { url: processed_url.to_string(), error: FetchError(e.to_string()) })
                    }
                }
            })
        }
        
        let Ok(processed_path) = Path::canonicalize(Path::new(request.url())) else {
            return Box::pin(async move {
                Err( ErrorResponse { url: request.url().to_string(), error: FetchError("Could not parse url".to_string()) } )
            })
        };

        Box::pin(async move {
            let path = processed_path;

            match fs::read(&path)
            {
                Ok(content) => {
                    let response: Box<dyn SuccessResponse> = Box::new(MyResponse {
                        url: path.to_str().unwrap_or("invalid").to_string(),
                        status: 200,
                        data: content,
                    });

                    Ok(response)
                },
                Err(e) => {
                    Err(ErrorResponse { url: path.to_str().unwrap_or("invalid").to_string(), error: IoError(e) })
                }
            }
        })
    }

    fn resolve_url(&self, _url: &str) -> Result<Url, ParseError> {
        panic!("resolve_url not implemented");
    }

    fn spawn_future(&mut self, future: OwnedFuture<(), Error>) {
        self.futures.push(future);
    }
    fn pre_process_url(&self, _url: Url) -> Url {
        panic!("pre_process_url not implemented");
    }

    fn connect_socket(
        &mut self,
        host: String,
        port: u16,
        _timeout: Duration,
        handle: SocketHandle,
        receiver: Receiver<Vec<u8>>,
        sender: Sender<SocketAction>,
    ) {

        match (host.as_str(), port) {
            ("127.0.13.37", 31337) => {
                let addr = "[::]:8080".to_string();
                let listener = std::net::TcpListener::bind(&addr).unwrap();
                println!("Listening on: {}", addr);

                loop {
                    let (stream, addr) = listener.accept().unwrap();

                    match fork::fork() {
                        Ok(fork::Fork::Parent(child)) => {
                            println!("Forked into child {} for connection {}", child, addr);
                        }
                        Ok(fork::Fork::Child) => {
                            unsafe { libc::alarm(60); }
                            self.connection_requests.push(ConnectionRequest::ExitstingStream(stream, addr, AVMConnection { ruffle_sender: sender, ruffle_receiver: receiver, ruffle_handle: handle } ));
                            break
                        },
                        Err(e) => eprintln!("Fork failed: {}", e),
                    }
                }
            }
            _ => {
                tracing::info!("other socket request by SWF");
                self.connection_requests.push(ConnectionRequest::Address(host, port, AVMConnection { ruffle_sender: sender, ruffle_receiver: receiver, ruffle_handle: handle } ));
            }
        };
    }
}
