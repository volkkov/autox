package com.gitshrl.autox;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.util.Base64;
import android.util.Log;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * A tiny HTTP/1.1 server bound to the device loopback, bridged to the host by
 * {@code adb forward}. Deliberately dependency-free (raw sockets) — the whole
 * server is one file and no third-party HTTP lib.
 *
 * Routes:
 *   GET /ping  -> "ok"
 *   GET /dump  -> the UI hierarchy XML (empty body for a dead tree)
 *
 * Single-threaded accept loop: dump requests are serial, and a dump reads a
 * consistent snapshot, so there is no concurrency to manage.
 */
final class RpcServer implements Runnable {

    private final AutoxAccessibilityService service;
    private final int port;
    private volatile boolean running = true;
    private ServerSocket serverSocket;
    private Thread thread;

    RpcServer(AutoxAccessibilityService service, int port) {
        this.service = service;
        this.port = port;
    }

    void start() {
        thread = new Thread(this, "autox-rpc");
        thread.setDaemon(true);
        thread.start();
    }

    void stop() {
        running = false;
        try {
            if (serverSocket != null) {
                serverSocket.close();
            }
        } catch (IOException ignored) {
        }
    }

    @Override
    public void run() {
        try {
            serverSocket = new ServerSocket();
            serverSocket.setReuseAddress(true);
            // Loopback only: reachable via `adb forward`, never from the network.
            serverSocket.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), port));
            while (running) {
                try {
                    handle(serverSocket.accept());
                } catch (IOException e) {
                    if (!running) {
                        break;
                    }
                    Log.w(AutoxAccessibilityService.TAG, "accept failed", e);
                }
            }
        } catch (IOException e) {
            Log.e(AutoxAccessibilityService.TAG, "RPC server crashed", e);
        }
    }

    private void handle(Socket socket) {
        try {
            socket.setSoTimeout(5000);
            BufferedReader in = new BufferedReader(new InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8));
            String requestLine = in.readLine();
            // Drain the request headers.
            String header;
            while ((header = in.readLine()) != null && !header.isEmpty()) {
                // ignored
            }

            String path = "/";
            if (requestLine != null) {
                String[] parts = requestLine.split(" ");
                if (parts.length >= 2) {
                    path = parts[1];
                }
            }

            String contentType = "text/plain; charset=utf-8";
            String body;
            if (path.startsWith("/dump")) {
                String xml = service.dumpHierarchy();
                body = xml == null ? "" : xml;
                contentType = "application/xml; charset=utf-8";
            } else if (path.startsWith("/ping")) {
                // Distinctive identity so the client can tell autox's server
                // apart from a foreign server squatting on the port.
                body = "autox-rpc 0.1.0";
            } else if (path.startsWith("/clipboard")) {
                // Readable because the app owns clipboard access as the active
                // IME (Android 10+ restricts it to the foreground app / IME).
                body = getClipboard();
            } else if (path.startsWith("/clipset")) {
                String b64 = queryParam(path, "b64");
                if (b64 != null) {
                    setClipboard(new String(Base64.decode(b64, Base64.URL_SAFE), StandardCharsets.UTF_8));
                }
                body = "ok";
            } else {
                body = "autox rpc";
            }

            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            OutputStream out = socket.getOutputStream();
            String head = "HTTP/1.1 200 OK\r\n"
                    + "Content-Type: " + contentType + "\r\n"
                    + "Content-Length: " + bytes.length + "\r\n"
                    + "Connection: close\r\n\r\n";
            out.write(head.getBytes(StandardCharsets.US_ASCII));
            out.write(bytes);
            out.flush();
        } catch (IOException ignored) {
        } finally {
            try {
                socket.close();
            } catch (IOException ignored) {
            }
        }
    }

    private static String queryParam(String path, String key) {
        int q = path.indexOf('?');
        if (q < 0) {
            return null;
        }
        for (String pair : path.substring(q + 1).split("&")) {
            int eq = pair.indexOf('=');
            if (eq > 0 && pair.substring(0, eq).equals(key)) {
                return pair.substring(eq + 1);
            }
        }
        return null;
    }

    private ClipboardManager clipboard() {
        return (ClipboardManager) service.getSystemService(Context.CLIPBOARD_SERVICE);
    }

    private String getClipboard() {
        final String[] out = {""};
        runOnMainSync(() -> {
            ClipboardManager cm = clipboard();
            if (cm != null && cm.hasPrimaryClip() && cm.getPrimaryClip().getItemCount() > 0) {
                CharSequence text = cm.getPrimaryClip().getItemAt(0).coerceToText(service);
                out[0] = text == null ? "" : text.toString();
            }
        });
        return out[0];
    }

    private void setClipboard(final String text) {
        runOnMainSync(() -> {
            ClipboardManager cm = clipboard();
            if (cm != null) {
                cm.setPrimaryClip(ClipData.newPlainText("autox", text));
            }
        });
    }

    /** ClipboardManager wants the main thread; run there and block briefly. */
    private void runOnMainSync(final Runnable r) {
        final CountDownLatch latch = new CountDownLatch(1);
        new Handler(Looper.getMainLooper()).post(() -> {
            try {
                r.run();
            } finally {
                latch.countDown();
            }
        });
        try {
            latch.await(2, TimeUnit.SECONDS);
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        }
    }
}
