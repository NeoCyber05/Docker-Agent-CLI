Introduction¶
Docker is the most popular containerization technology. When used correctly, it can enhance security compared to running applications directly on the host system. However, certain misconfigurations can reduce security levels or introduce new vulnerabilities.

The aim of this cheat sheet is to provide a straightforward list of common security errors and best practices to assist in securing your Docker containers.

Rules
RULE #0 - Keep Host and Docker up to date¶
To protect against known container escape vulnerabilities like Leaky Vessels, which typically result in the attacker gaining root access to the host, it's vital to keep both the host and Docker up to date. This includes regularly updating the host kernel as well as the Docker Engine.

This is due to the fact that containers share the host's kernel. If the host's kernel is vulnerable, the containers are also vulnerable. For example, the kernel privilege escalation exploit, Dirty COW, executed inside a well-insulated container would still result in root access on a vulnerable host.

RULE #1 - Do not expose the Docker daemon socket (even to the containers)¶
Docker socket /var/run/docker.sock is the UNIX socket that Docker is listening to. This is the primary entry point for the Docker API. The owner of this socket is root. Giving someone access to it is equivalent to giving unrestricted root access to your host.

Do not enable tcp Docker daemon socket. If you are running docker daemon with -H tcp://0.0.0.0:XXX or similar you are exposing unencrypted and unauthenticated direct access to the Docker daemon, if the host is internet connected this means the docker daemon on your computer can be used by anyone from the public internet. If you really, really have to do this, you should secure it. Check how to do this following Docker official documentation.

Do not expose /var/run/docker.sock to other containers. If you are running your docker image with -v /var/run/docker.sock://var/run/docker.sock or similar, you should change it. Remember that mounting the socket read-only is not a solution but only makes it harder to exploit. Equivalent in the docker compose file is something like this:

volumes:
  - "/var/run/docker.sock:/var/run/docker.sock"
RULE #2 - Set a user¶
Configuring the container to use an unprivileged user is the best way to prevent privilege escalation attacks. This can be accomplished in three different ways as follows:

During runtime using -u option of docker run command e.g.:
docker run -u 4000 alpine
During build time. Simply add user in Dockerfile and use it. For example:
FROM alpine
RUN groupadd -r myuser && useradd -r -g myuser myuser
#    <HERE DO WHAT YOU HAVE TO DO AS A ROOT USER LIKE INSTALLING PACKAGES ETC.>
USER myuser
Enable user namespace support (--userns-remap=default) in Docker daemon
More information about this topic can be found at Docker official documentation. For additional security, you can also run in rootless mode, which is discussed in Rule #11.

In Kubernetes, this can be configured in Security Context using the runAsUser field with the user ID e.g:

apiVersion: v1
kind: Pod
metadata:
  name: example
spec:
  containers:
    - name: example
      image: gcr.io/google-samples/node-hello:1.0
      securityContext:
        runAsUser: 4000 # <-- This is the pod user ID
As a Kubernetes cluster administrator, you can configure a hardened default using the Restricted level with built-in Pod Security admission controller, if greater customization is desired consider using Admission Webhooks or a third party alternative.

RULE #3 - Limit capabilities (Grant only specific capabilities, needed by a container)¶
Linux kernel capabilities are a set of privileges that can be used by privileged. Docker, by default, runs with only a subset of capabilities. You can change it and drop some capabilities (using --cap-drop) to harden your docker containers, or add some capabilities (using --cap-add) if needed. Remember not to run containers with the --privileged flag - this will add ALL Linux kernel capabilities to the container.

The most secure setup is to drop all capabilities --cap-drop all and then add only required ones. For example:

docker run --cap-drop all --cap-add CHOWN alpine
And remember: Do not run containers with the --privileged flag!!!

In Kubernetes this can be configured in Security Context using capabilities field e.g:

apiVersion: v1
kind: Pod
metadata:
  name: example
spec:
  containers:
    - name: example
      image: gcr.io/google-samples/node-hello:1.0
      securityContext:
        capabilities:
          drop:
            - ALL
          add: ["CHOWN"]
As a Kubernetes cluster administrator, you can configure a hardened default using the Restricted level with built-in Pod Security admission controller, if greater customization is desired consider using Admission Webhooks or a third party alternative.

RULE #4 - Prevent in-container privilege escalation¶
Always run your docker images with --security-opt=no-new-privileges in order to prevent privilege escalation. This will prevent the container from gaining new privileges via setuid or setgid binaries.

In Kubernetes, this can be configured in Security Context using allowPrivilegeEscalation field e.g.:

apiVersion: v1
kind: Pod
metadata:
  name: example
spec:
  containers:
    - name: example
      image: gcr.io/google-samples/node-hello:1.0
      securityContext:
        allowPrivilegeEscalation: false
As a Kubernetes cluster administrator, you can configure a hardened default using the Restricted level with built-in Pod Security admission controller, if greater customization is desired consider using Admission Webhooks or a third party alternative.

RULE #5 - Be mindful of Inter-Container Connectivity¶
Inter-Container Connectivity (icc) is enabled by default, allowing all containers to communicate with each other through the docker0 bridged network. Instead of using the --icc=false flag with the Docker daemon, which completely disables inter-container communication, consider defining specific network configurations. This can be achieved by creating custom Docker networks and specifying which containers should be attached to them. This method provides more granular control over container communication.

For detailed guidance on configuring Docker networks for container communication, refer to the Docker Documentation.

In Kubernetes environments, Network Policies can be used to define rules that regulate pod interactions within the cluster. These policies provide a robust framework to control how pods communicate with each other and with other network endpoints. Additionally, Network Policy Editor simplifies the creation and management of network policies, making it more accessible to define complex networking rules through a user-friendly interface.

RULE #5a - Be careful when mapping container ports to the host with firewalls like UFW¶
UFW (Uncomplicated Firewall) is a popular host-based firewall for Linux. A common misconception is that firewall rules protect all inbound traffic — including traffic destined for Docker containers. However, Docker manages its own iptables and nftables rules directly and bypasses UFW entirely. Note that other tools that use iptables or nftables can also have conflicts similar to UFW. If you are using other firewall tools, you should check if they are working correctly.

When you publish a port with -p 8000:8000, Docker inserts iptables rules that open that port to all interfaces and all source addresses, and these rules are typically accepted before explicit firewall DENY rules are applied. As a result, traffic may be allowed through regardless of any DENY rules you have set, which can unintentionally expose container services to the public internet.

Recommended Mitigations¶
Option 1 — Bind published ports to localhost only:

Bind the host side of the port mapping to 127.0.0.1 so the service is only reachable locally, not from external networks:

# Vulnerable: exposes port on all interfaces
docker run -p 8000:8000 myimage

# Safe: binds only to localhost
docker run -p 127.0.0.1:8000:8000 myimage
In a Docker Compose file:

services:
  web:
    image: myimage
    ports:
      - "127.0.0.1:8000:8000"  # safe — localhost only
Option 2 — Use ufw-docker (or equivalent) to enforce firewall rules over Docker networks:

For UFW specifically, the ufw-docker project provides a script and supplemental iptables rules that patch Docker's networking to respect UFW policies, allowing you to use standard UFW commands to control traffic to containers:

# Install ufw-docker integration rules
sudo ufw-docker install

# Allow external access to a specific container port
sudo ufw-docker allow mycontainer 8000/tcp
Refer to the Docker and iptables documentation for a deeper explanation of how Docker interacts with the host firewall.

RULE #6 - Use Linux Security Module (seccomp, AppArmor, or SELinux) for Runtime Security¶
First of all, do not disable default security profile! Always start with Docker’s or your host’s default profile as a baseline.

Security Profile Recommendations:

Seccomp: Restrict syscalls to the minimum required for your container. Use Docker’s default seccomp profile as a starting point and customize per workload. Docker Seccomp

AppArmor: Apply per-container AppArmor profiles to enforce mandatory access controls. Docker AppArmor

SELinux: Enable SELinux on the host and ensure containers are labeled properly. Enforce SELinux policies to prevent unauthorized access to host resources. SELinux Guide for Docker

Runtime Security Improvements:

Behavioral Monitoring: Use tools like Falco, Tetragon, or Cilium eBPF to detect unexpected or malicious container activity. Examples: Unexpected exec calls, privilege escalation attempts, unusual network connections.

Anomaly Detection: Continuously monitor container processes, filesystem changes, and network activity to identify abnormal patterns in real time.

Kubernetes Security Context: Configure pods or containers with seccomp and AppArmor profiles in Kubernetes. Configure a Security Context for a Pod or Container

RULE #7 - Limit resources (memory, CPU, file descriptors, processes, restarts)¶
The best way to avoid DoS attacks is by limiting resources. You can limit memory, CPU, maximum number of restarts (--restart=on-failure:<number_of_restarts>), maximum number of file descriptors (--ulimit nofile=<number>) and maximum number of processes (--ulimit nproc=<number>).

Check documentation for more details about ulimits

You can also do this for Kubernetes: Assign Memory Resources to Containers and Pods, Assign CPU Resources to Containers and Pods and Assign Extended Resources to a Container

RULE #8 - Set filesystem and volumes to read-only¶
Run containers with a read-only filesystem using --read-only flag. For example:

docker run --read-only alpine sh -c 'echo "whatever" > /tmp'
If an application inside a container has to save something temporarily, combine --read-only flag with --tmpfs like this:

docker run --read-only --tmpfs /tmp alpine sh -c 'echo "whatever" > /tmp/file'
The Docker Compose compose.yml equivalent would be:

version: "3"
services:
  alpine:
    image: alpine
    read_only: true
Equivalent in Kubernetes in Security Context:

apiVersion: v1
kind: Pod
metadata:
  name: example
spec:
  containers:
    - name: example
      image: gcr.io/google-samples/node-hello:1.0
      securityContext:
        readOnlyRootFilesystem: true
In addition, if the volume is mounted only for reading mount them as a read-only It can be done by appending :ro to the -v like this:

docker run -v volume-name:/path/in/container:ro alpine
Or by using --mount option:

docker run --mount source=volume-name,destination=/path/in/container,readonly alpine
RULE #9 - Integrate container scanning tools into your CI/CD pipeline¶
CI/CD pipelines are a crucial part of the software development lifecycle and should include various security checks such as lint checks, static code analysis, and container scanning.

Many issues can be prevented by following some best practices when writing the Dockerfile. However, adding a security linter as a step in the build pipeline can go a long way in avoiding further headaches. Some issues that are commonly checked are:

Ensure a USER directive is specified
Ensure the base image version is pinned
Ensure the OS packages versions are pinned
Avoid the use of ADD in favor of COPY
Avoid curl bashing in RUN directives
References:

Docker Baselines on DevSec
Use the Docker command line
Overview of Docker Compose v2 CLI
Configuring Logging Drivers
View logs for a container or service
Dockerfile Security Best Practices
Container scanning tools are especially important as part of a successful security strategy. They can detect known vulnerabilities, secrets and misconfigurations in container images and provide a report of the findings with recommendations on how to fix them. Some examples of popular container scanning tools are:

Free
Clair
Grype
Trivy
Commercial
Snyk (open source and free option available)
Anchore (open source and free option available)
Docker Scout (open source and free option available)
JFrog XRay
Qualys
To detect secrets in images:

ggshield (open source and free option available)
Gitleaks (open source)
TruffleHog (open source)
To detect misconfigurations in Kubernetes:

kubeaudit
kubesec.io
kube-bench
To detect misconfigurations in Docker:

inspec.io
dev-sec.io
Docker Bench for Security
RULE #10 - Keep the Docker daemon logging level at info¶
By default, the Docker daemon is configured to have a base logging level of info. This can be verified by checking the daemon configuration file /etc/docker/daemon.json for thelog-level key. If the key is not present, the default logging level is info. Additionally, if the docker daemon is started with the --log-level option, the value of the log-level key in the configuration file will be overridden. To check if the Docker daemon is running with a different log level, you can use the following command:

ps aux | grep '[d]ockerd.*--log-level' | awk '{for(i=1;i<=NF;i++) if ($i ~ /--log-level/) print $i}'
Setting an appropriate log level, configures the Docker daemon to log events that you would want to review later. A base log level of 'info' and above would capture all logs except the debug logs. Until and unless required, you should not run docker daemon at the 'debug' log level.

Rule #11 - Run Docker in rootless mode¶
Rootless mode ensures that the Docker daemon and containers are running as an unprivileged user, which means that even if an attacker breaks out of the container, they will not have root privileges on the host, which in turn substantially limits the attack surface. This is different to userns-remap mode, where the daemon still operates with root privileges.

Evaluate the specific requirements and security posture of your environment to determine if rootless mode is the best choice for you. For environments where security is a paramount concern and the limitations of rootless mode do not interfere with operational requirements, it is a strongly recommended configuration. Alternatively consider using Podman as an alternative to Docker.

Rootless mode allows running the Docker daemon and containers as a non-root user to mitigate potential vulnerabilities in the daemon and the container runtime. Rootless mode does not require root privileges even during the installation of the Docker daemon, as long as the prerequisites are met.

Read more about rootless mode and its limitations, installation and usage instructions on Docker documentation page.

RULE #12 - Utilize Docker Secrets for Sensitive Data Management¶
Docker Secrets provide a secure way to store and manage sensitive data such as passwords, tokens, and SSH keys. Using Docker Secrets helps in avoiding the exposure of sensitive data in container images or in runtime commands.

docker secret create my_secret /path/to/super-secret-data.txt
docker service create --name web --secret my_secret nginx:latest
Or for Docker Compose:

version: "3.8"
secrets:
  my_secret:
    file: ./super-secret-data.txt
services:
  web:
    image: nginx:latest
    secrets:
      - my_secret
While Docker Secrets generally provide a secure way to manage sensitive data in Docker environments, this approach is not recommended for Kubernetes, where secrets are stored in plaintext by default. In Kubernetes, consider using additional security measures such as etcd encryption, or third-party tools. Refer to the Secrets Management Cheat Sheet for more information.

RULE #13 - Enhance Supply Chain Security¶
Building on the principles in Rule #9, enhancing supply chain security involves implementing additional measures to secure the entire lifecycle of container images from creation to deployment. Some of the key practices include:

Image Provenance: Document the origin and history of container images to ensure traceability and integrity.
SBOM Generation: Create a Software Bill of Materials (SBOM) for each image, detailing all components, libraries, and dependencies for transparency and vulnerability management.
Image Signing: Digitally sign images to verify their integrity and authenticity, establishing trust in their security.
Trusted Registry: Store the documented, signed images with their SBOMs in a secure registry that enforces strict access controls and supports metadata management.
Secure Deployment: Implement secure deployment polices, such as image validation, runtime security, and continuous monitoring, to ensure the security of the deployed image