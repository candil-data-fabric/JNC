package com.github.candildatafabric.jnc;

import java.io.File;
import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketException;

import javax.net.SocketFactory;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import net.schmizz.sshj.SSHClient;
import net.schmizz.sshj.transport.verification.HostKeyVerifier;
import net.schmizz.sshj.transport.verification.OpenSSHKnownHosts;
import net.schmizz.sshj.transport.verification.PromiscuousVerifier;
import net.schmizz.sshj.userauth.UserAuthException;

/**
 * A SSH NETCONF connection class. Can be used whenever {@link NetconfSession}
 * intends to use SSH for its transport.
 * <p>
 * Example:
 *
 * <pre>
 * SSHConnection ssh = new SSHConnection(&quot;127.0.0.1&quot;, 2023);
 * ssh.authenticateWithPassword(&quot;ola&quot;, &quot;secret&quot;);
 * SSHSession tr = new SSHSession(ssh);
 * NetconfSession dev1 = new NetconfSession(tr);
 * </pre>
 */
public class SSHConnection implements AutoCloseable {

    protected final Logger log = LoggerFactory.getLogger(getClass());
    SSHClient client;

    public SSHConnection() {
        client = new SSHClient();
    }

    public SSHConnection setHostVerification(String knownHostsFile) throws IOException {
        HostKeyVerifier verifier;
        if (knownHostsFile == null) {
            verifier = new PromiscuousVerifier();
        } else {
            verifier = new OpenSSHKnownHosts(new File(knownHostsFile));
            log.debug("using OpenSSH known-hosts file {}", knownHostsFile);
        }
        client.addHostKeyVerifier(verifier);
        return this;
    }

    /**
     * By default we connect to the IANA registered port for NETCONF which is
     * 830
     *
     * @param host Host or IP address to connect to
     */
    public SSHConnection connect(String host) throws IOException, JNCException {
        return connect(host, 830, 0);
    }

    /**
     * This method establishes an SSH connection to a host, once the connection
     * is established it must be authenticated.
     *
     * @param host Host name.
     * @param port Port number to connect to.
     */
    public SSHConnection connect(String host, int port) throws IOException,
                                                 JNCException {
        return connect(host, port, 0);
    }

    /**
     * This method establishes an SSH connection to a host, once the connection
     * is established it must be authenticated.
     *
     * @param host Host name.
     * @param port Port number to connect to.
     * @param connectTimeout
     */
    public SSHConnection connect(String host, int port, int connectTimeout)
        throws IOException, JNCException {
        return connect(host, port, connectTimeout, 0);
    }

    /**
     * This method establishes an SSH connection to a host, once the connection
     * is established it must be authenticated.
     *
     * @param host Host name.
     * @param port Port number to connect to.
     * @param connectTimeout Connection timeout timer. Connect the underlying
     *            TCP socket to the server with the given timeout value
     *            (non-negative, in milliseconds). Zero means no timeout.
     * @param kexTimeout Key exchange timeout timer. Timeout for complete
     *            connection establishment (non-negative, in milliseconds).
     *            Zero means no timeout. The timeout counts until the first
     *            key-exchange round has finished.
     * @throws IOException In case of a timeout (either connectTimeout or
     *             kexTimeout) a SocketTimeoutException is thrown.
     *             <p>
     *             An exception may also be thrown if the connection was
     *             already successfully connected (no matter if the connection
     *             broke in the mean time) and you invoke
     *             <code>connect()</code> again without having called
     *             {@link #close()} first.
     */
    public SSHConnection connect(String host, int port, int connectTimeout,
                        int kexTimeout) throws IOException {
        client.setTimeout(connectTimeout);
        client.getTransport().setTimeoutMs(kexTimeout);
        client.connect(host, port);
        return this;
    }

    /**
     * Wait for a call-home from a NETCONF server and establish an SSH
     * connection to it with infinite timeouts and the IANA-registered
     * NETCONF call-home port 4334.
     */
     public InetSocketAddress waitCallHome() throws IOException {
         return waitCallHome(0);
    }

    public InetSocketAddress waitCallHome(int waitTimeout) throws IOException {
        return waitCallHome(waitTimeout, 0);
    }

    public InetSocketAddress waitCallHome(int waitTimeout, int kexTimeout) throws IOException {
        return waitCallHome(waitTimeout, kexTimeout, 4334);
    }

    /**
     * Wait for a call-home from a NETCONF server and establish an SSH
     * connection to it.
     *
     * @param waitTimeout Wait timeout. Wait for incoming connection
     *            for given number of milliseconds, 0 for infinite
     *            timeout.
     * @param kexTimeout Key exchange timeout timer. Timeout for complete
     *            connection establishment (non-negative, in milliseconds).
     *            Zero means no timeout. The timeout counts until the first
     *            key-exchange round has finished.
     * @param port Port number to be opened.
     * @throws IOException In case of a timeout (either connectTimeout or
     *             kexTimeout) a SocketTimeoutException is thrown.
     *             <p>
     *             An exception may also be thrown if the connection was
     *             already successfully connected (no matter if the connection
     *             broke in the mean time) and you invoke
     *             <code>connect()</code> again without having called
     *             {@link #close()} first.
     */
    public InetSocketAddress waitCallHome(int waitTimeout, int kexTimeout, int port)
        throws IOException {
        try (ServerSocket svrSocket = new ServerSocket(port)) {
            try {
                svrSocket.setSoTimeout(waitTimeout);
            } catch (SocketException e) {
                throw new IOException("Failed to set socket timeout", e);
            }
            Socket socket = svrSocket.accept();
            client.setSocketFactory(new SocketFactory() {
                    @Override
                    public Socket createSocket() {
                        return socket;
                    }
                    @Override
                    public Socket createSocket(InetAddress host, int port) {
                        return socket;
                    }
                    @Override
                    public Socket createSocket(InetAddress address, int port,
                                               InetAddress localAddress, int localPort) {
                        return socket;
                    }
                    @Override
                    public Socket createSocket(String host, int port) {
                        return socket;
                    }
                    @Override
                    public Socket createSocket(String host, int port,
                                               InetAddress localHost, int localPort) {
                        return socket;
                    }
                });
            client.getTransport().setTimeoutMs(kexTimeout);
            InetSocketAddress addr = new InetSocketAddress(socket.getInetAddress().getHostAddress(),
                                                           socket.getPort());
            client.connect(addr.getHostName(), addr.getPort());
            return addr;
        }
    }

    SSHClient getClient() {
        return client;
    }

    /**
     * Authenticate with regular username pass.
     *
     * @param user User name.
     * @param password Password.
     *
     **/
    public void authenticateWithPassword(String user, String password)
            throws IOException, JNCException {
        try {
            client.authPassword(user, password);
        } catch (UserAuthException e) {
            throw new JNCException(JNCException.AUTH_FAILED, e);
        }
    }

    /**
     * Authenticate with the name of a file containing the private key.
     *
     * TODO: key file with a passphrase support.
     *
     * @param user User name.
     * @param keyFile File name.
     **/
    public void authenticateWithPublicKeyFile(String user, String keyFile)
        throws IOException, JNCException {
        try {
            client.authPublickey(user, keyFile);
        } catch (UserAuthException e) {
            throw new JNCException(JNCException.AUTH_FAILED, e);
        }
    }

    // /**
    //  * Authenticate with a private key. See ganymed docs for full explanation,
    //  * use null for password if the key doesn't have a passphrase.
    //  *
    //  * @param user User name.
    //  * @param pemPrivateKey Private key.
    //  * @param pass Passphrase.
    //  **/
    // public void authenticateWithPublicKey(String user, char[] pemPrivateKey,
    //         String pass) throws IOException, JNCException {
    //     if (!connection.authenticateWithPublicKey(user, pemPrivateKey, pass)) {
    //         throw new JNCException(JNCException.AUTH_FAILED, this);
    //     }
    // }

    /**
     * Closes the SSH session/connection.
     */
    @Override
    public void close() {
        try {
            client.close();
        } catch (IOException e) {
            System.out.println("Exception in close(): " + e);
        }
    }

}
