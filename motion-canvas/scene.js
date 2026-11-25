import { Circle, Img, Rect, Txt, makeScene2D } from '@motion-canvas/2d';
import { Logger, Renderer, RendererResult, ValueDispatcher, Vector2, all, easeOutCubic, waitFor } from '@motion-canvas/core';

window.renderScene = async (spec) => {
  const { width, height, duration, fps, title, detail, template, image } = spec;
  const unit = Math.min(width, height);
  const accent = '#67e8f9';
  const scene = makeScene2D(function* (view) {
    const intro = Math.min(0.65, duration / 3);
    if (template !== 'comparison') {
      const picture = new Img({ src: image, width, height, scale: 1 });
      view.add(picture);
      if (template === 'highlight') {
        const target = new Circle({
          width: unit * 0.32, height: unit * 0.32, lineWidth: unit * 0.006, stroke: accent,
          x: (spec.focus_x - 0.5) * width, y: (spec.focus_y - 0.5) * height, opacity: 0, scale: 1.32,
        });
        view.add(target);
        yield* all(target.opacity(1, intro), target.scale(1, intro, easeOutCubic));
      } else {
        yield* all(
          picture.scale(1.24, intro, easeOutCubic),
          picture.position([(0.5 - spec.focus_x) * width * 0.24, (0.5 - spec.focus_y) * height * 0.24], intro),
        );
      }
      if (title) {
        const caption = new Txt({
          text: title, y: height * 0.29, width: width * 0.79, textWrap: true,
          fontSize: unit * 0.052, fontWeight: 700, fill: '#fff', stroke: '#090e1a',
          lineWidth: unit * 0.009, opacity: 0,
        });
        view.add(caption);
        yield* caption.opacity(1, intro / 2);
      }
    } else {
      const frame = new Rect({ width: width * 0.83, height: unit * 0.53, fill: '#172238', radius: unit * 0.025 });
      const left = new Txt({ text: title, width: width * 0.33, x: -width * 0.21, textWrap: true, textAlign: 'center',
        fontSize: unit * 0.075, fontWeight: 700, fill: '#ecf2ff', opacity: 0 });
      const right = new Txt({ text: detail, width: width * 0.33, x: width * 0.21, textWrap: true, textAlign: 'center',
        fontSize: unit * 0.075, fontWeight: 700, fill: accent, opacity: 0 });
      const arrow = new Txt({ text: '→', fontSize: unit * 0.066, fill: accent, opacity: 0 });
      view.add(frame);
      frame.add([left, arrow, right]);
      yield* left.opacity(1, intro / 2);
      yield* all(arrow.opacity(1, intro / 2), right.opacity(1, intro, easeOutCubic));
    }
    yield* waitFor(duration);
  });

  const exporter = {
    id: 'shortpipeline-frames',
    async create() {
      return {
        async handleFrame(canvas, frame) {
          await window.saveFrame(frame, canvas.toDataURL('image/jpeg', 0.93).split(',')[1]);
        },
      };
    },
  };
  const logger = new Logger();
  let renderError;
  logger.onLogged.subscribe((event) => {
    if (event.level === 'error') renderError = event.message;
  });
  const description = { ...scene, name: 'scene' };
  description.onReplaced = new ValueDispatcher(description);
  const project = {
    name: 'ShortPipeline', scenes: [description], logger, plugins: [],
    meta: { rendering: { exporter: { exporters: [exporter] } } },
  };
  const renderer = new Renderer(project);
  let result;
  renderer.onFinished.subscribe((value) => { result = value; });
  await renderer.render({
    name: project.name, fps, size: new Vector2(width, height), resolutionScale: 1,
    colorSpace: 'srgb', background: '#0b1020', range: [0, (Math.round(duration * fps) - 1) / fps],
    exporter: { name: exporter.id },
  });
  if (result !== RendererResult.Success) throw new Error(renderError || 'Motion Canvas render failed');
};
