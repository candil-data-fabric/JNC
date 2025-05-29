package com.github.candildatafabric.jnc;

import java.io.IOException;
import java.io.Serializable;
import java.net.InetSocketAddress;
import java.util.ArrayList;
import java.util.List;

/**
 * This class provides features for managing a device with NETCONF.
 * A device has a list of users {@link DeviceUser} which contain information
 * about how to connect to the device.
 * <p>
 * Associated to a device is a list of named sessions, each session is a
 * {@link NetconfSession} session inside an SSH channel. We can have several
 * sessions to one device. It can for example make sense to have one session
 * open to the configuration db(s) and another session open for NETCONF
 * notifications Typical usage pattern is:
 * </p>
 *
 * <pre>
 * String localUserName = &quot;joe&quot;;
 * DeviceUser duser = new DeviceUser(localUserName, &quot;admin&quot;, &quot;secret&quot;);
 * Device dev = new Device(&quot;mydev&quot;, duser, &quot;netconf.tail-f.com&quot;, 8023);
 * dev.connect(localUserName);
 * dev.newSession(&quot;cfg&quot;);
 * Element someConfigTree = makeMyTree();
 * dev.getSession(&quot;cfg&quot;).editConfig(someConfigTree);
 * </pre>
 *
 * <p>Another option is to let the Device instance to be built via a
 * NETCONF call-home mechanism. This can be done like this:</p>
 *
 * <pre><code>Device dev = new Device.CallHome(&quot;mydev&quot;)
 *     .setWaitTimeout(10000)
 *     .waitForCallHome();
 * dev.addUser(new DeviceUser(localUserName, &quot;admin&quot;, &quot;admin&quot;));
 * dev.authenticate(localUserName);
 * dev.newSession(&quot;cfg&quot;);</code></pre>
 *
 * <p>Note that the newly created Device instance is connected, but
 * does not have any users and is not yet authenticated, so it needs
 * to be done once call-home successfully completes.</p>
 *
 * <p>
 * Once we have a new session, we also get a configTree (Element) that we can
 * use to accumulate changes in for the session. This usually handy since the
 * manager code typically consists of bits and pieces that manipulate different
 * parts of the configuration. Then it is convenient to let all manager code
 * add Elements to the session specifig config tree. The tree can be accessed
 * through the getConfig(String) method.
 * </p>
 *
 * <p>
 * This class also provides basic backlog funtionality. If the device
 * configuration is changed and the device is currently down for some reason, a
 * backlog with the configuration change can be saved and run later when the
 * device comes up again.
 * </p>
 */

public class Device implements Serializable, AutoCloseable {

    private static final long serialVersionUID = 1L;

    /**
     * named session specific connection data
     */
    static private class SessionConnData {
        String sessionName;
        SSHSession sshSession;
        NetconfSession session;

        SessionConnData(String n, SSHSession t, NetconfSession s) {
            sessionName = n;
            session = s;
            sshSession = t;
        }
    }

    /**
     * named session specific config data
     */
    static private class SessionTree {
        String sessionName;
        Element configTree;

        SessionTree(String n) {
            sessionName = n;
            configTree = null;
        }
    }

    /**
     * The name of the device, or its IP address.
     */
    public String name;

    /**
     * An SSH Connection to this device.
     */
    protected transient SSHConnection con;

    /**
     * The NETCONF sessions (channels) for this device.
     */
    protected transient List<SessionConnData> connSessions;
    protected transient List<SessionTree> trees;

    /**
     * A list of configuration changes. The backlog is saved when a
     * configuration change is made and the device is down, so that it can be
     * re-sent later when the device comes up again.
     */
    protected List<Element> backlog;

    /**
     * A list of users.
     */
    protected List<DeviceUser> users;

    /**
     * ip address as string
     */
    protected String mgmt_ip;

    /**
     * port number
     */
    protected int mgmt_port;

    /**
     * Time to wait for read, in milliseconds.
     */
    protected int defaultReadTimeout;

    /**
     * Constructor for the Device with on initial user. We need at least one
     * DeviceUser in order to be able to connect.
     */
    public Device(String name, DeviceUser user, String mgmtIp, int mgmtPort) {

        this.name = name;
        users = new ArrayList<DeviceUser>();
        users.add(user);
        this.mgmt_ip = mgmtIp;
        this.mgmt_port = mgmtPort;
        backlog = new ArrayList<Element>();
        connSessions = new ArrayList<SessionConnData>();
        trees = new ArrayList<SessionTree>();
    }

    /**
     * Constructor for the Device with on initial user. We need at least one
     * DeviceUser in order to be able to connect. Thus if this constructor is
     * used to create the Device we must use addUser() priot to connecting.
     */
    public Device(String name, String mgmtIp, int mgmtPort) {

        this.name = name;
        users = new ArrayList<DeviceUser>();
        this.mgmt_ip = mgmtIp;
        this.mgmt_port = mgmtPort;
        backlog = new ArrayList<Element>();
        connSessions = new ArrayList<SessionConnData>();
        trees = new ArrayList<SessionTree>();
    }

    /**
     * Builder for Device instances using the NETCONF call-home
     * mechanism.
     */
    public static class CallHome {
        private String name;
        private int waitTimeout = 0;
        private int kexTimeout = 0;
        private String knownHostsFile = null;
        private int port = 4334;

        public CallHome(String deviceName) {
            name = deviceName;
        }
        public CallHome setWaitTimeout(int waitTimeout) {
            this.waitTimeout = waitTimeout;
            return this;
        }
        public CallHome setKexTimeout(int kexTimeout) {
            this.kexTimeout = kexTimeout;
            return this;
        }
        public CallHome setVerify() {
            return setKnownHostsFile("~/.ssh/known_hosts");
        }
        public CallHome setKnownHostsFile(String knownHostsFile) {
            this.knownHostsFile = knownHostsFile;
            return this;
        }
        public CallHome setPort(int port) {
            this.port = port;
            return this;
        }
        public Device waitForCallHome() throws IOException {
            SSHConnection con = new SSHConnection().setHostVerification(knownHostsFile);
            InetSocketAddress addr = con.waitCallHome(waitTimeout, kexTimeout, port);
            Device dev = new Device(name, addr.getHostName(), addr.getPort());
            dev.con = con;
            return dev;
        }
    }

    /**
     * If Device is stored on disk as a serialized object, we need to init the
     * transient variables after we read a Device from disk.
     */
    public void initTransients() {
        backlog = new ArrayList<Element>();
        connSessions = new ArrayList<SessionConnData>();
        trees = new ArrayList<SessionTree>();
    }

    /**
     * Adds a user to the Device list of users.
     */
    public void addUser(DeviceUser user) {
        users.add(user);
    }

    /**
     * Return the list of users.
     */
    public List<DeviceUser> getUsers() {
        return users;
    }

    /**
     * Clears the accumulation config tree for a named NETCONF session
     *
     * @param sessionName symbolic Name of the session
     */
    public void clearConfig(String sessionName) {
        final SessionTree t = getTreeData(sessionName);
        t.configTree = null;
    }

    /**
     * Returns the accumulated config tree for a named NETCONF session. This
     * feature is a convenience feature. It makes sense to perform a series of
     * changes towards a device and accumulate the changes in a single tree. A
     * configuration tree is associated to a named session/ssh channel.
     *
     * If a session is closed, we may still have accumulated config data
     * associated to the session. This method retieves this data although the
     * ssh socket to the server may be dead.
     *
     * @param sessionName symbolic Name of the session
     */
    public Element getConfig(String sessionName) {
        return getTreeData(sessionName).configTree;
    }

    /**
     * Sets the readTimeout associated to a named session
     *
     * @param sessionName symbolic Name of the session
     * @param readTimeout timeout in milliseconds
     */
    public void setReadTimeout(String sessionName, int readTimeout) {
        final SessionConnData p = getConnData(sessionName);
        p.sshSession.setReadTimeout(readTimeout);
    }

    /**
     * Gets the readTimeout associated to a named session
     *
     * @param sessionName symbolic Name of the session
     * @return timeout in milliseconds
     */
    public long getReadTimeout(String sessionName) {
        final SessionConnData p = getConnData(sessionName);
        return p.sshSession.getReadTimeout();
    }

    /**
     * Check if the named session have a saved configuration tree.
     *
     * @param sessionName symbolic Name of the session
     */
    public boolean hasConfig(String sessionName) {
        final SessionTree t = getTreeData(sessionName);
        return t.configTree != null;
    }

    /**
     * Sets the accumulation config tree for a named session
     *
     * @param sessionName symbolic Name of the session
     * @param e The config tree to insert.
     */
    public void setConfig(String sessionName, Element e) {
        final SessionTree t = getTreeData(sessionName);
        t.configTree = e;
    }

    /**
     * Checks if a backlog is saved for this device.
     */
    public boolean hasBacklog() {
        return !backlog.isEmpty();
    }

    /**
     * Whenever new NetconfSession objects are created through newSession() set
     * this timeout value (milliseconds) as the readTimeout value
     */
    public void setDefaultReadTimeout(int defaultReadTimeout) {
        this.defaultReadTimeout = defaultReadTimeout;
    }

    /**
     * Close the named session associated with this device. Note, this does not
     * close the socket, it closes the SSH channel which is a considerably
     * cheaper operation. The method also clears any accumulated configuration
     * data we have.
     *
     * @param sessionName symbolic Name of the session
     */
    public void closeSession(String sessionName) {
        for (int i = 0; i < connSessions.size(); i++) {
            final SessionConnData p = connSessions.get(i);
            if (p.sessionName.equals(sessionName)) {
                closeSession(p);
                connSessions.remove(i);
                return;
            }
        }
    }

    private void closeSession(SessionConnData data) {
        if (data != null && data.session != null) {
            data.sshSession.close();
        }
        if (data != null) {
            clearConfig(data.sessionName);
        }
    }

    /**
     * end all NETCONF sessions and close the SSH socket associated to this
     * device It also clears all accumulated config trees.
     */
    @Override
    public void close() {
        for (final SessionConnData d : connSessions) {
            closeSession(d);
        }
        connSessions = new ArrayList<SessionConnData>();
        for (SessionTree tree : trees) {
            final SessionTree t = tree;
            t.configTree = null;
        }
        // we keep the named config trees
        if (con != null) {
            con.close();
            con = null;
        }
    }

    /**
     * Checks if this device has any sessions with specified name.
     */
    public boolean hasSession(String name) {
        return getSession(name) != null;
    }

    /**
     * Returns a named NetconfSession for this NETCONF enabled device. The
     * NetconfSession implements (through it's subclass NetconfSession) the
     * getTransport() method. Thus we can get to the underlying ganymed Session
     * object as:
     *
     * <pre>
     * Session s = ((SSHSession) d.getSession(&quot;cfg&quot;).getTransport()).getSession();
     * </pre>
     *
     * This is required to monitor the ganymed Session object for EOF
     */
    public NetconfSession getSession(String sessionName) {
        final SessionConnData data = getConnData(sessionName);
        return (data == null) ? null : data.session;
    }

    /**
     * Returns a named SSHSession for this NETCONF enabled device. We need the
     * {@link SSHSession} object if we for example wish to check if an ssh
     * session is ready to read.
     */
    public SSHSession getSSHSession(String sessionName) {
        final SessionConnData data = getConnData(sessionName);
        return (data == null) ? null : data.sshSession;
    }

    /**
     * This method finds the {@link DeviceUser} associated to the localUser
     * user name and SSH connects to the device, this method must be called
     * prior to establishing any sessions (channels).
     *
     * The connection requires host key check.
     */
    public void connect(String localUser) throws IOException, JNCException {
        connect(localUser, 0, true);
    }

    /**
     * Connect to the device with given connection timeout.
     *
     * @param localUser The name of a local (for the EMS) user
     * @param connectTimeout Initial connection timeout (in milliseconds)
     * @param verifyHost If true, check host's key against the standard
     * known_hosts file
     */
    public void connect(String localUser, int connectTimeout, boolean verifyHost)
            throws IOException, JNCException {
        connect(localUser, connectTimeout, verifyHost ? "~/.ssh/known_hosts" : null);
    }

    /**
     * Connect to the device with given connection timeout and given known hosts
     * file.
     *
     * @param localUser The name of a local (for the EMS) user
     * @param connectTimeout Initial connection timeout (in milliseconds)
     * @param knownHostsFile If non-null, check host's key against the
     * known_hosts file
     */
    public void connect(String localUser, int connectTimeout, String knownHostsFile)
            throws IOException, JNCException {
        con = new SSHConnection()
            .setHostVerification(knownHostsFile)
            .connect(mgmt_ip, mgmt_port, connectTimeout);
        authenticate(localUser);
    }

    public void authenticate(String localUser) throws IOException, JNCException {
        DeviceUser u = null;
        for (final DeviceUser u2 : users) {
            if (u2.getLocalUser().equals(localUser)) {
                u = u2;
                break;
            }
        }
        if (u == null) {
            throw new JNCException(JNCException.AUTH_FAILED, "No such user: "
                    + localUser);
        }
        auth(u);
    }

    /**
     * This method is mostly interesting if we want to use the backlog
     * functionality. A typical sequence towards a device is connect(),
     * newSession(). If connect fails, because the device is down, we still
     * might want to have a config tree to accumulate changes in although we
     * have no connection to the device. The getConfig(String) method searches
     * in a list of configTrees, thus we can have named configTrees although
     * there is no existing session towards the device.
     */
    public void newSessionConfigTree(String sessionName) {
        if (getTreeData(sessionName) == null) {
            trees.add(new SessionTree(sessionName));
        }
    }

    /**
     * Creates a new named NETCONF session. Each named session corresponds to
     * one SSH channel towards the agent
     *
     * @param sessionName symbolic Name of the session
     */
    public void newSession(String sessionName) throws JNCException,
            IOException, YangException {
        newSession(null, sessionName);
    }

    /**
     * Creates a new named NETCONF session We must not have an existing session
     * with the same name. Thus when we reconnect a Device, we must first call
     * closeSession(sessionName);
     *
     * @param sub IO subscriber for trace messages.
     * @param sessionName symbolic Name of the session
     */

    public void newSession(IOSubscriber sub, String sessionName)
            throws JNCException, IOException {
        newSession(sub, sessionName, true);
    }

    public void newSession(IOSubscriber sub, String sessionName, boolean use11)
            throws JNCException, IOException {
        final SessionConnData data = getConnData(sessionName);
        // always create the configTree
        newSessionConfigTree(sessionName);

        // Check that we don't already have a session with that name
        if (data != null) {
            int errCode = YangException.BAD_SESSION_NAME;
            throw new YangException(errCode, sessionName);
        }

        final YangXMLParser parser = new YangXMLParser();
        final SSHSession sshSession = new SSHSession(con, defaultReadTimeout);
        if (sub != null) {
            sshSession.addSubscriber(sub);
        }
        final NetconfSession session = new NetconfSession(sshSession, parser, use11);
        final SessionConnData d = new SessionConnData(sessionName,
                sshSession, session);
        connSessions.add(d);

        if (!backlog.isEmpty()) {
            runBacklog(sessionName);
        }
    }

    /**
     * Adds the given configuration tree to the list of backlogs.
     *
     * @param e Config tree to be saved.
     */
    public void addBackLog(Element e) {
        backlog.add(e);
    }

    /**
     * Return the backlog.
     */
    public Element[] getBacklog() {
        if (backlog != null && !backlog.isEmpty()) {
            final Element[] a = new Element[backlog.size()];
            return backlog.toArray(a);
        }
        return new Element[0];
    }

    /**
     * Run the backlog. A backlog is typically saved when a configuration
     * change is made (for several devices) and the device is down. The backlog
     * saves the configuration update so that it can be re-sent later. This
     * method runs the saved backlog. It is automatically run whenever we
     * succeeed in creating a new sesssion.
     *
     * @param sessionName symbolic Name of the session
     */
    public void runBacklog(String sessionName) throws IOException,
            JNCException {
        System.out.println("Running backlog ");
        final SessionConnData data = getConnData(sessionName);
        if (data == null) {
            throw new YangException(YangException.BAD_SESSION_NAME,
                    sessionName);
        }
        for (int i = 0; i < backlog.size(); i++) {
            final Element e = backlog.get(i);
            System.out.println("Bacloh " + e.toXMLString());
            data.session.editConfig(e);
            backlog.remove(i);
        }
    }

    /**
     * Returns a string with information about this device.
     */
    @Override
    public String toString() {
        StringBuffer s = new StringBuffer("Device: ");
        s.append(name).append(' ').append(mgmt_ip).append(':').append(mgmt_port).append('\n');
        for (final SessionConnData p : connSessions) {
            s.append("   session: ").append(p.sessionName);
        }
        return s.toString();
    }

    private SessionConnData getConnData(String sessionName) {
        for (final SessionConnData p : connSessions) {
            if (p.sessionName.equals(sessionName)) {
                return p;
            }
        }
        return null;
    }

    private SessionTree getTreeData(String sessionName) {
        for (final SessionTree t : trees) {
            if (t.sessionName.equals(sessionName)) {
                return t;
            }
        }
        return null;
    }

    private void auth(DeviceUser currentUser)
            throws IOException, JNCException {
        if (currentUser.getPassword() != null) {
            con.authenticateWithPassword(
                    currentUser.getRemoteuser(),
                    currentUser.getPassword());
        } else if (currentUser.getPemFile() != null) {
            con.authenticateWithPublicKeyFile(
                    currentUser.getRemoteuser(),
                    currentUser.getPemFile().getAbsolutePath());
        }
    }

}
