# executor-java/Dockerfile
# ── Build stage ──────────────────────────────────────────────────────────────
FROM maven:3.9.6-eclipse-temurin-17 AS build

WORKDIR /build
COPY pom.xml .
# Download dependencies (cached layer)
RUN mvn dependency:go-offline -q

COPY src/ ./src/
RUN mvn package -DskipTests -q

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM eclipse-temurin:17-jre-jammy

LABEL maintainer="Anas Lahraoui <lahraoui.forex@example.com>"
LABEL description="NeuralForex-Pro Executor – order execution and risk management"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=build /build/target/executor-1.0.0.jar app.jar

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "app.jar"]
