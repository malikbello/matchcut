// Camera director: the shots a football broadcast uses, driven by the ball.
//   broadcast  the main gantry camera on the halfway line, panning and zooming with play
//   tactical   high and wide behind the main camera, the whole shape of both teams
//   goal       low behind the goal the ball is attacking, for chances and replays
// Moves are critically damped springs, so pans ease in and out like a camera operator.
// Shots are framed as operators frame them, in metres of play across the picture, not in lens
// angle: the main camera shows about 46 m on a widescreen feed and about 20 m on a vertical one,
// tightening near the boxes, and leads the play in the direction the ball is travelling.
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
    this.prevBall = null;
    this.lead = new THREE.Vector3();
  }

  // the vertical field of view that shows `metres` of play across the picture at `dist`
  fovFor(metres, dist) {
    const aspect = this.camera.aspect || 16 / 9;
    const half = Math.atan(metres / 2 / Math.max(dist, 1));
    return THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(half) / aspect));
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
    // lead room: look a little ahead of where the ball is going (a second of travel, at most 7 m)
    if (this.prevBall && dt > 0 && dt < 1) {
      const vx = (ball.x - this.prevBall.x) / dt;
      const vz = (ball.z - this.prevBall.z) / dt;
      const lx = THREE.MathUtils.clamp(vx * 0.8, -7, 7);
      const lz = THREE.MathUtils.clamp(vz * 0.5, -4, 4);
      this.lead.x = spring(this.lead.x, lx, 1.2, dt);
      this.lead.z = spring(this.lead.z, lz, 1.2, dt);
    }
    this.prevBall = { x: ball.x, z: ball.z };
    const vertical = (this.camera.aspect || 1.78) < 1;
    const nearBox = Math.min(1, Math.max(0, (Math.abs(bx) - 20) / 25));
    let pos;
    let look;
    let fov;
    if (this.mode === "tactical") {
      // on the front edge of the main stand roof, looking down on the whole shape of both teams
      pos = new THREE.Vector3(bx * 0.35, 42, W / 2 + 9);
      look = new THREE.Vector3(bx * 0.42, 0, -6);
      fov = 52;
    } else if (this.mode === "tight") {
      // the close camera on the ball, from the main-stand side like a handheld touchline camera
      pos = new THREE.Vector3(ball.x - 3, 5.5, ball.z + 15);
      look = new THREE.Vector3(ball.x, 0.9, ball.z);
      fov = 34;
    } else if (this.mode === "goal") {
      // behind the goal, framing the play around the ball (a vertical feed comes closer)
      const side = this.goalSide ?? (bx >= 0 ? 1 : -1);
      pos = new THREE.Vector3(side * (L / 2 + (vertical ? 9 : 14)), vertical ? 5 : 6.5, bz * 0.3);
      look = new THREE.Vector3(side * (L / 2 - 16) * 0.5 + bx * 0.5, 1, bz * 0.8);
      fov = this.fovFor(vertical ? 24 : 40, pos.distanceTo(look));
    } else {
      // gantry in the main stand on the halfway side: pans with the ball and leads the play;
      // the picture is sized in metres of play, so a vertical feed keeps players readable
      pos = new THREE.Vector3(bx * 0.55, 21, W / 2 + 19);
      look = new THREE.Vector3(bx + this.lead.x, 0, (vertical ? bz * 0.85 : bz * 0.55 - 2) + this.lead.z);
      const metres = vertical ? THREE.MathUtils.lerp(22, 17, nearBox) : THREE.MathUtils.lerp(46, 34, nearBox);
      fov = this.fovFor(metres, pos.distanceTo(look));
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
