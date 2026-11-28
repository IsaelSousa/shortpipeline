import {
  BoxGeometry, ConeGeometry, CylinderGeometry, DirectionalLight, HemisphereLight,
  Mesh, MeshStandardMaterial, OrthographicCamera, Scene, SphereGeometry, TorusGeometry, WebGLRenderer,
} from 'three';
import { window01 } from './util.js';

const RAD = Math.PI / 180;
const geometries = {
  box: () => new BoxGeometry(1.6, 1.6, 1.6),
  sphere: () => new SphereGeometry(1, 32, 20),
  cylinder: () => new CylinderGeometry(0.8, 0.8, 1.7, 32),
  cone: () => new ConeGeometry(0.9, 1.8, 32),
  torus: () => new TorusGeometry(0.75, 0.23, 20, 48),
};

export function createThreeLayer(width, height) {
  let renderer;
  try {
    renderer = new WebGLRenderer({ alpha: true, antialias: true, preserveDrawingBuffer: true });
  } catch (error) {
    throw new Error('WebGL 2 indisponível para a camada 3D do ShortPipeline', { cause: error });
  }
  renderer.setSize(width, height, false);
  renderer.setClearAlpha(0);
  const camera = new OrthographicCamera(-1, 1, 1, -1, 0.1, 50);
  const layers = new WeakMap();
  const shapes = new Map();

  function createScene(layer) {
    const scene = new Scene();
    scene.add(new HemisphereLight(0xe9f4ff, 0x66608a, 1.55));
    const key = new DirectionalLight(0xffefd9, 2.6);
    key.position.set(-4, 5, 6);
    scene.add(key);
    const rim = new DirectionalLight(0x8dbaff, 1.8);
    rim.position.set(4, 2, -5);
    scene.add(rim);
    const meshes = layer.objects.map((object) => {
      if (!shapes.has(object.shape)) shapes.set(object.shape, geometries[object.shape]());
      const mesh = new Mesh(shapes.get(object.shape), new MeshStandardMaterial({
        color: object.color ?? '#38BDF8', metalness: 0.15, roughness: 0.42,
      }));
      mesh.position.set(...(object.position ?? [0, 0, 0]));
      scene.add(mesh);
      return mesh;
    });
    return { scene, meshes };
  }

  return (ctx, layer, time, local) => {
    if (!layers.has(layer)) layers.set(layer, createScene(layer));
    const { scene, meshes } = layers.get(layer);
    for (const [i, object] of layer.objects.entries()) {
      const { rotation = [0, 0, 0], spin = [0, 0, 0], scale = 1, reveal } = object;
      const amount = reveal ? window01(local, reveal.start ?? 0, reveal.dur ?? 0.45, 'out') : 1;
      const mesh = meshes[i];
      mesh.visible = amount > 0;
      mesh.scale.setScalar(scale * amount);
      mesh.rotation.set(...rotation.map((angle, axis) => (angle + spin[axis] * time) * RAD));
    }
    const halfHeight = (layer.view_height ?? 7) / 2;
    const halfWidth = halfHeight * width / height;
    camera.left = -halfWidth;
    camera.right = halfWidth;
    camera.top = halfHeight;
    camera.bottom = -halfHeight;
    camera.updateProjectionMatrix();
    const azimuth = (18 + (layer.orbit ?? 0) * time) * RAD;
    camera.position.set(10 * Math.sin(azimuth), 4, 10 * Math.cos(azimuth));
    camera.lookAt(0, 0, 0);
    renderer.render(scene, camera);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(renderer.domElement, 0, 0);
  };
}
