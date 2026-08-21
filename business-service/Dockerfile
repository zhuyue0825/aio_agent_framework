FROM eclipse-temurin:21-jdk AS build
WORKDIR /workspace
COPY .mvn .mvn
COPY mvnw pom.xml ./
RUN chmod +x mvnw && ./mvnw -q -DskipTests dependency:go-offline
COPY src src
RUN ./mvnw -q -DskipTests package

FROM eclipse-temurin:21-jre
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system aio \
    && adduser --system --ingroup aio aio
COPY --from=build /workspace/target/business-service-0.1.0-SNAPSHOT.jar /app/app.jar
USER aio
EXPOSE 8081
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
