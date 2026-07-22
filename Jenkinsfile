// Minimal CI/CD for App-1 (serviot-devices-api): build -> test -> deploy.
//
// Prereqs in Jenkins:
//   - Docker available on the agent (the Jenkins box has it).
//   - Credential 'app-ssh' = SSH Username with private key
//       username: ubuntu, key: the serviot-key.pem for the app box.
//
// Deploy target is the app EC2; code is shipped over SSH (tar), then the prod
// compose rebuilds + restarts the container. .env on the box is left untouched.

pipeline {
  agent any

  options { timestamps() }

  environment {
    IMAGE    = "serviot-devices-api"
    APP_HOST = "ubuntu@100.56.97.79"
    APP_DIR  = "/opt/serviot/devices-api"
  }

  stages {
    stage('Build') {
      steps {
        sh 'docker build -t $IMAGE:$BUILD_NUMBER .'
      }
    }

    stage('Test') {
      steps {
        // Ephemeral Postgres + the built image, run pytest against it.
        sh '''
          export IMAGE=$IMAGE:$BUILD_NUMBER
          docker compose -p ci -f docker-compose.ci.yml up -d --wait
          docker run --rm --network ci_default -e BASE_URL=http://api:8000 \
            -v "$PWD":/w -w /w python:3.12-slim \
            sh -c "pip install -q pytest && python -m pytest -q tests/"
        '''
      }
      post {
        always { sh 'docker compose -p ci -f docker-compose.ci.yml down -v || true' }
      }
    }

    stage('Deploy') {
      steps {
        sshagent(['app-ssh']) {
          sh '''
            tar czf - --exclude=.git --exclude=.env --exclude=.pytest_cache . \
              | ssh -o StrictHostKeyChecking=no $APP_HOST \
                "mkdir -p $APP_DIR && tar xzf - -C $APP_DIR && \
                 cd $APP_DIR && sudo docker compose -f docker-compose.prod.yml up -d --build --force-recreate"
          '''
        }
      }
    }
  }

  post {
    success { echo "Deployed build $BUILD_NUMBER to $APP_HOST" }
    failure { echo "Pipeline failed at build $BUILD_NUMBER" }
  }
}
