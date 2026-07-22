// CI/CD for App-1 (serviot-devices-api): build -> test -> deploy (+ auto-rollback).
//
// Prereqs in Jenkins:
//   - Docker on the agent (Jenkins box has it).
//   - Credential 'app-ssh' = SSH Username with private key (user ubuntu), the
//     serviot-key.pem for the app box.
//
// Deploy is git-based: the box pulls the new commit, rebuilds via the prod
// compose, then a health check runs. If /health isn't 200, the box resets to
// the previous commit and redeploys — last-known-good rollback. .env on the box
// (RDS creds) is gitignored and never touched.

pipeline {
  agent any

  options { timestamps() }

  environment {
    IMAGE    = "serviot-devices-api"
    APP_HOST = "ubuntu@10.20.0.135"   // app box PRIVATE IP (same VPC as Jenkins)
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
        withCredentials([sshUserPrivateKey(credentialsId: 'app-ssh', keyFileVariable: 'SSH_KEY')]) {
          // The remote script is a quoted heredoc (<<'REMOTE') so nothing
          // expands locally — the box runs it verbatim.
          sh '''
            ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no $APP_HOST 'bash -s' <<'REMOTE'
set -e
APP_DIR=/home/ubuntu/serviot-demo
HEALTH=http://127.0.0.1:8000/health
cd "$APP_DIR"

deploy() { sudo docker compose -f docker-compose.prod.yml up -d --build --force-recreate; }
healthy() {
  for i in $(seq 1 10); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "$HEALTH" || echo 000)
    [ "$code" = "200" ] && return 0
    sleep 3
  done
  return 1
}

PREV=$(git rev-parse HEAD)
git fetch origin main
git reset --hard origin/main
deploy

if healthy; then
  echo "deploy OK, healthy"
else
  echo "health check FAILED -> rolling back to $PREV"
  git reset --hard "$PREV"
  deploy
  healthy && echo "rolled back to last-known-good" || echo "ROLLBACK ALSO UNHEALTHY"
  exit 1
fi
REMOTE
          '''
        }
      }
    }
  }

  post {
    success { echo "Deployed build $BUILD_NUMBER to $APP_HOST" }
    failure { echo "Build $BUILD_NUMBER failed (rolled back if past deploy)" }
  }
}
