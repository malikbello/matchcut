// Camera director: the shots a football broadcast uses, driven by the ball.
//   broadcast  the main gantry camera on the halfway line, panning and zooming with play
//   tactical   high and wide behind the main camera, the whole shape of both teams
//   goal       low behind the goal the ball is attacking, for chances and replays
// Moves are critically damped springs, so pans ease in and out like a camera operator.
import * as THREE from "three";
import { L, W } from "./pitch.js";

const spring = (cur, target, rate, dt) => cur + (target - cur) * (1 - Math.exp(-rate * dt));

export class Director {
  constructor(camera) {
    this.camera = camera;
    this.mode = "broadcast";
    this.look = new THREE.Vector3(0, 0, 0);
    this.pos = new THREE.Vector3(0, 21, W / 2 + 19);
    this.fov = 30;
  }

  setMode(mode) {
    this.mode = mode;
  }

  // a hard cut: the next frame jumps straight to the new shot, as a vision mixer does
  cut() {
    this.snap = true;
  }

  // replays keep the behind-goal camera on the goal that was scored in, wherever the ball is
  lockGoal(side) {
    this.goalSide = side;
  }

  update(ball, dt) {
    if (this.snap) {
      dt = 1e3;
      this.snap = false;
    }
    const bx = THREE.MathUtils.clamp(ball.x, -L / 2, L / 2);
    const bz = THREE.MathUtils.clamp(ball.z, -W / 2, W / 2);
    let pos;
    let look;
    let fov;
    if (this.mode === "tactical") {
      pos = new THREE.Vector3(bx * 0.35, 62, W / 2 + 58);
      look = new THREE.Vector3(bx * 0.4, 0, -2);
      fov = 42;
    } else if (this.mode === "tight") {
      // the close camera on the ball, from the main-stand side like a handheld touchline camera
      pos = new THREE.Vector3(ball.x - 3, 5.5, ball.z + 15);
      look = new THREE.Vector3(ball.x, 0.9, ball.z);
      fov = 34;
    } else if (this.mode === "goal") {
      const side = this.goalSide ?? (bx >= 0 ? 1 : -1);
      pos = new THREE.Vector3(side * (L / 2 + 16), 7, bz * 0.25);
      look = new THREE.Vector3(side * (L / 2 - 18), 1, bz * 0.6);
      fov = 38;
    } else {
      // gantry: pans with the ball, tightens near the boxes, stays wide in midfield
      pos = new THREE.Vector3(bx * 0.55, 21, W / 2 + 19); // gantry in the main stand, on the touchline at the bottom of the 2D view
      look = new THREE.Vector3(bx * 0.92, 0, bz * 0.55 - 2);
      fov = THREE.MathUtils.lerp(26, 18, Math.min(1, Math.abs(bx) / (L / 2)));
    }
    this.pos.x = spring(this.pos.x, pos.x, 2.2, dt);
    this.pos.y = spring(this.pos.y, pos.y, 2.2, dt);
    this.pos.z = spring(this.pos.z, pos.z, 2.2, dt);
    this.look.x = spring(this.look.x, look.x, 3.0, dt);
    this.look.y = spring(this.look.y, look.y, 3.0, dt);
    this.look.z = spring(this.look.z, look.z, 3.0, dt);
    this.fov = spring(this.fov, fov, 1.5, dt);
    this.camera.position.copy(this.pos);
    this.camera.fov = this.fov;
    this.camera.updateProjectionMatrix();
    this.camera.lookAt(this.look);
  }
}
