//! Submarine battle PoC: sink the golden boats in a big walled patch of open water.
//! W/S engine telegraph (reverse / stop / slow / mid / full), A/D set the rudder (it stays put,
//! C centres it), arrows turn and elevate the gun (the red disc marks where a shell lands),
//! SPACE = shell (3 hits kill, surfaced only), T = torpedo (1 hit kills, also when dived),
//! F dive to periscope depth, R = restart. Third-person camera behind the boat.
//! Touch devices get on-screen buttons for the same actions.

use std::collections::HashSet;
use std::f32::consts::TAU;

use bevy::light::NotShadowCaster;
use bevy::mesh::VertexAttributeValues;
use bevy::prelude::*;
use bevy::world_serialization::WorldInstanceReady;

const ARENA: f32 = 40.0;
const DIVE_DEPTH: f32 = 0.32;
const HIT_RADIUS: f32 = 0.9;
const SHELL_SPEED: f32 = 14.0;
const GRAVITY: f32 = 5.0;
const TORPEDO_SPEED: f32 = 3.0;
const TORPEDO_DEPTH: f32 = -0.1;
// Gun pivot on the hull, and the barrel tip's distance from it (see art/blender/uboat.py).
const TRUNNION: Vec3 = Vec3::new(0.42, 0.265, 0.0);
const BARREL: f32 = 0.31;
// Engine telegraph: reverse, stop, slow, mid, full.
const THROTTLE: [(&str, f32); 5] = [("REVERSE", -1.0), ("STOP", 0.0), ("SLOW", 1.0), ("MID", 2.0), ("FULL", 3.2)];
const STOP: usize = 1; // index of "STOP" in THROTTLE
const ENEMIES: [(f32, f32, f32); 8] = [
    (14.0, -8.0, 0.5),
    (-12.0, 10.0, 2.0),
    (22.0, 16.0, 4.0),
    (-20.0, -16.0, 1.0),
    (2.0, -24.0, 3.0),
    (30.0, -2.0, 5.0),
    (-6.0, 26.0, 0.2),
    (18.0, 28.0, 2.5),
];

fn main() -> AppExit {
    App::new()
        .add_plugins(DefaultPlugins.set(WindowPlugin {
            primary_window: Some(Window {
                title: "Submarine Battle".into(),
                fit_canvas_to_parent: true,
                ..default()
            }),
            ..default()
        }))
        .insert_resource(ClearColor(Color::srgb(0.10, 0.45, 0.62)))
        .insert_resource(GlobalAmbientLight { color: Color::srgb(0.85, 0.92, 1.0), brightness: 600.0, ..default() })
        .insert_resource(Touch { on: is_touch_device(), ..default() })
        .init_resource::<Controls>()
        .add_systems(Startup, setup)
        .add_systems(
            Update,
            (read_input, drive, fire, marker, fly, trail, explode, animate, follow, wake, bubbles, restart, hud, touch_ui)
                .chain(),
        )
        .run()
}

#[derive(Component)]
struct Round; // everything that goes away on restart

#[derive(Component)]
struct Player {
    throttle: usize, // index into THROTTLE
    speed: f32,
    yaw: f32,
    rudder: f32, // -1..1, stays where the player left it
    depth: f32,  // 0 surfaced .. 1 periscope depth
    dived: bool,
    gun_yaw: f32, // relative to the hull
    gun_pitch: f32,
    kick: f32,
    prop: f32,
    shell_cd: f32,
    torpedo_cd: f32,
}

impl Default for Player {
    fn default() -> Self {
        Self {
            throttle: STOP,
            speed: 0.0,
            yaw: 0.0,
            rudder: 0.0,
            depth: 0.0,
            dived: false,
            gun_yaw: 0.0,
            gun_pitch: 0.0,
            kick: 0.0,
            prop: 0.0,
            shell_cd: 0.0,
            torpedo_cd: 0.0,
        }
    }
}

#[derive(Component)]
struct Enemy {
    hp: i32,
}

#[derive(Component)]
struct Projectile {
    vel: Vec3,
    gravity: f32,
    ramp: f32, // seconds to reach full speed (0 = at once)
    age: f32,
    life: f32,
    damage: i32,
}

#[derive(Component)]
struct Torpedo(f32); // time since the last bubble

#[derive(Component)]
struct TorpedoProp;

#[derive(Component)]
struct Explosion {
    t: f32,
    size: f32,
}

#[derive(Component)]
struct Bubble {
    life: f32,
    size: f32,
}

#[derive(Component)]
struct Hud;

#[derive(Component)]
struct Marker; // where the next shell lands

/// Animatable nodes of the player's model, named like the Blender groups.
#[derive(Component)]
enum Part {
    Gun,
    Barrel,
    Recoil,
    Periscope,
    Propeller,
    Rudder,
    Cloth(usize),
}

#[derive(Component)]
struct Rest(Vec3);

#[derive(Resource)]
struct Look {
    bubble: Handle<Mesh>,
    foam: Handle<StandardMaterial>,
}

fn model(assets: &AssetServer, name: &str) -> WorldAssetRoot {
    WorldAssetRoot(assets.load(GltfAssetLabel::Scene(0).from_asset(format!("models/{name}.glb"))))
}

fn setup(
    mut commands: Commands,
    assets: Res<AssetServer>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<StandardMaterial>>,
) {
    commands.spawn((Camera3d::default(), Transform::from_xyz(-34.0, 2.0, 0.0).looking_at(Vec3::new(-27.0, 0.0, 0.0), Vec3::Y)));
    commands.spawn((
        DirectionalLight { illuminance: 9000.0, shadow_maps_enabled: true, ..default() },
        Transform::from_xyz(2.0, 4.0, 3.0).looking_at(Vec3::ZERO, Vec3::Y),
    ));

    // Faceted water: normals come from a bumpy surface, then the bumps are flattened, so the
    // facets catch the light differently and you can see the boat gliding over them.
    let mut water = Plane3d::default().mesh().size(240.0, 240.0).subdivisions(100).build();
    if let Some(VertexAttributeValues::Float32x3(pos)) = water.attribute_mut(Mesh::ATTRIBUTE_POSITION) {
        for p in pos.iter_mut() {
            p[1] = ((p[0] * 0.9).sin() + (p[2] * 0.7 + p[0] * 0.3).sin()) * 0.25;
        }
    }
    water.duplicate_vertices();
    water.compute_flat_normals();
    if let Some(VertexAttributeValues::Float32x3(pos)) = water.attribute_mut(Mesh::ATTRIBUTE_POSITION) {
        for p in pos.iter_mut() {
            p[1] *= 0.15;
        }
    }
    commands.spawn((
        Mesh3d(meshes.add(water)),
        MeshMaterial3d(materials.add(StandardMaterial {
            base_color: Color::srgba(0.10, 0.45, 0.62, 0.6),
            alpha_mode: AlphaMode::Blend,
            perceptual_roughness: 0.6,
            ..default()
        })),
        Transform::from_xyz(0.0, -0.03, 0.0),
        NotShadowCaster,
    ));

    // Hard limits: a red wall on each side.
    let cube = meshes.add(Cuboid::default());
    let red = materials.add(StandardMaterial { base_color: Color::srgb(0.9, 0.2, 0.15), ..default() });
    let len = ARENA * 2.0 + 0.3;
    for (at, size) in [
        (Vec3::new(0.0, 0.1, ARENA), Vec3::new(len, 0.3, 0.15)),
        (Vec3::new(0.0, 0.1, -ARENA), Vec3::new(len, 0.3, 0.15)),
        (Vec3::new(ARENA, 0.1, 0.0), Vec3::new(0.15, 0.3, len)),
        (Vec3::new(-ARENA, 0.1, 0.0), Vec3::new(0.15, 0.3, len)),
    ] {
        commands.spawn((Mesh3d(cube.clone()), MeshMaterial3d(red.clone()), Transform::from_translation(at).with_scale(size)));
    }
    commands.spawn((
        Hud,
        Text::new(""),
        TextFont::from_font_size(16.0),
        TextColor(Color::WHITE),
        Node { position_type: PositionType::Absolute, left: Val::Px(12.0), top: Val::Px(10.0), ..default() },
    ));
    commands.spawn((
        Marker,
        Mesh3d(meshes.add(Cylinder::new(0.3, 0.02))),
        MeshMaterial3d(materials.add(StandardMaterial {
            base_color: Color::srgba(1.0, 0.2, 0.15, 0.6),
            alpha_mode: AlphaMode::Blend,
            unlit: true,
            ..default()
        })),
        NotShadowCaster,
    ));
    commands.insert_resource(Look {
        bubble: meshes.add(Sphere::new(0.5).mesh().ico(1).unwrap()),
        foam: materials.add(StandardMaterial {
            base_color: Color::srgba(1.0, 1.0, 1.0, 0.5),
            alpha_mode: AlphaMode::Blend,
            unlit: true,
            ..default()
        }),
    });
    spawn_touch_ui(&mut commands);
    spawn_round(&mut commands, &assets);
}

fn spawn_round(commands: &mut Commands, assets: &AssetServer) {
    commands
        .spawn((Round, Player::default(), Transform::from_xyz(-ARENA + 8.0, 0.0, 0.0), model(assets, "uboat")))
        .observe(find_parts);
    for (x, z, yaw) in ENEMIES {
        commands.spawn((
            Round,
            Enemy { hp: 3 },
            Transform::from_xyz(x, 0.0, z).with_rotation(Quat::from_rotation_y(yaw)),
            model(assets, "uboat_gold"),
        ));
    }
}

fn find_parts(
    ready: On<WorldInstanceReady>,
    children: Query<&Children>,
    nodes: Query<(&Name, &Transform)>,
    mut commands: Commands,
) {
    for e in children.iter_descendants(ready.entity) {
        let Ok((name, tf)) = nodes.get(e) else { continue };
        let part = match name.as_str() {
            "Gun" => Part::Gun,
            "GunBarrel" => Part::Barrel,
            "GunRecoil" => Part::Recoil,
            "Periscope" => Part::Periscope,
            "Propeller" => Part::Propeller,
            "Rudder" => Part::Rudder,
            "FlagCloth1" => Part::Cloth(0),
            "FlagCloth2" => Part::Cloth(1),
            "FlagCloth3" => Part::Cloth(2),
            _ => continue,
        };
        commands.entity(e).insert((part, Rest(tf.translation)));
    }
}

fn find_torpedo_prop(ready: On<WorldInstanceReady>, children: Query<&Children>, names: Query<&Name>, mut commands: Commands) {
    for e in children.iter_descendants(ready.entity) {
        if names.get(e).is_ok_and(|n| n.as_str() == "TorpedoProp") {
            commands.entity(e).insert(TorpedoProp);
        }
    }
}

/// What the player wants this frame, from keyboard, mouse or touch buttons.
#[derive(Resource, Default)]
struct Controls {
    faster: bool,
    slower: bool,
    stop: bool,
    rudder: f32, // +1 left
    centre: bool,
    gun_yaw: f32, // +1 left
    gun_pitch: f32,
    shell: bool,
    torpedo: bool,
    dive: bool,
    restart: bool,
}

#[derive(Clone, Copy, PartialEq, Eq, Hash)]
enum Action {
    Faster,
    Slower,
    Stop,
    RudderLeft,
    RudderRight,
    Centre,
    GunLeft,
    GunRight,
    GunUp,
    GunDown,
    Shell,
    Torpedo,
    Dive,
    Restart,
}

/// On-screen buttons: `on` once the device has a touchscreen; `held` and `tapped` come from presses.
#[derive(Resource, Default)]
struct Touch {
    on: bool,
    held: HashSet<Action>,
    tapped: HashSet<Action>,
}

#[derive(Component)]
struct TouchRoot;

#[derive(Component)]
struct TouchButton(Action);

#[cfg(target_arch = "wasm32")]
fn is_touch_device() -> bool {
    web_sys::window().is_some_and(|w| w.navigator().max_touch_points() > 0)
}

#[cfg(not(target_arch = "wasm32"))]
fn is_touch_device() -> bool {
    false
}

fn read_input(
    keys: Res<ButtonInput<KeyCode>>,
    mouse: Res<ButtonInput<MouseButton>>,
    touches: Res<Touches>,
    mut touch: ResMut<Touch>,
    mut c: ResMut<Controls>,
) {
    let fingers = touches.iter().next().is_some();
    if fingers {
        touch.on = true;
    }
    if !fingers && !mouse.pressed(MouseButton::Left) {
        touch.held.clear(); // a lost release must never leave a button stuck
    }
    let held = |a| touch.held.contains(&a) as i32 as f32;
    let tap = |a| touch.tapped.contains(&a);
    let key = |k| keys.pressed(k) as i32 as f32;
    *c = Controls {
        faster: keys.just_pressed(KeyCode::KeyW) || tap(Action::Faster),
        slower: keys.just_pressed(KeyCode::KeyS) || tap(Action::Slower),
        stop: keys.just_pressed(KeyCode::KeyX) || tap(Action::Stop),
        rudder: (key(KeyCode::KeyA) - key(KeyCode::KeyD) + held(Action::RudderLeft) - held(Action::RudderRight)).clamp(-1.0, 1.0),
        centre: keys.just_pressed(KeyCode::KeyC) || tap(Action::Centre),
        gun_yaw: (key(KeyCode::ArrowLeft) - key(KeyCode::ArrowRight) + held(Action::GunLeft) - held(Action::GunRight)).clamp(-1.0, 1.0),
        gun_pitch: (key(KeyCode::ArrowUp) - key(KeyCode::ArrowDown) + held(Action::GunUp) - held(Action::GunDown)).clamp(-1.0, 1.0),
        shell: keys.pressed(KeyCode::Space) || mouse.pressed(MouseButton::Left) || held(Action::Shell) > 0.0 || tap(Action::Shell),
        torpedo: keys.just_pressed(KeyCode::KeyT) || mouse.just_pressed(MouseButton::Right) || tap(Action::Torpedo),
        dive: keys.just_pressed(KeyCode::KeyF) || tap(Action::Dive),
        restart: keys.just_pressed(KeyCode::KeyR) || tap(Action::Restart),
    };
    touch.tapped.clear();
}

fn drive(c: Res<Controls>, time: Res<Time>, player: Single<(&mut Player, &mut Transform)>) {
    let dt = time.delta_secs();
    let (mut p, mut tf) = player.into_inner();
    if c.faster {
        p.throttle = (p.throttle + 1).min(THROTTLE.len() - 1);
    }
    if c.slower {
        p.throttle = p.throttle.saturating_sub(1);
    }
    if c.stop {
        p.throttle = STOP;
    }
    let dive_factor = if p.dived { 0.7 } else { 1.0 };
    let want = THROTTLE[p.throttle].1 * dive_factor;
    p.speed += (want - p.speed) * (0.8 * dt).min(1.0);
    p.rudder = (p.rudder + c.rudder * dt).clamp(-1.0, 1.0);
    if c.centre {
        p.rudder = 0.0;
    }
    p.yaw += p.rudder * 0.3 * p.speed * dt; // the rudder only bites while moving
    p.gun_yaw += c.gun_yaw * dt;
    p.gun_pitch = (p.gun_pitch + c.gun_pitch * 0.5 * dt).clamp(-0.1, 0.8);
    if c.dive {
        p.dived = !p.dived;
    }
    let target = if p.dived { 1.0 } else { 0.0 };
    p.depth += (target - p.depth).clamp(-1.5 * dt, 1.5 * dt);
    p.shell_cd -= dt;
    p.torpedo_cd -= dt;
    p.kick = (p.kick - 2.5 * dt).max(0.0);
    p.prop = (p.prop + p.speed * 8.0 * dt) % TAU;

    let forward = Quat::from_rotation_y(p.yaw) * Vec3::X;
    tf.translation += forward * p.speed * dt;
    let limit = ARENA - 1.0;
    tf.translation.x = tf.translation.x.clamp(-limit, limit);
    tf.translation.z = tf.translation.z.clamp(-limit, limit);
    tf.translation.y = -DIVE_DEPTH * p.depth;
    tf.rotation = Quat::from_rotation_y(p.yaw);
}

fn shoot<'a>(commands: &'a mut Commands, assets: &AssetServer, name: &str, at: Vec3, p: Projectile) -> EntityCommands<'a> {
    let rotation = Quat::from_rotation_arc(Vec3::X, p.vel.normalize());
    commands.spawn((Round, p, Transform::from_translation(at).with_rotation(rotation), model(assets, name)))
}

/// Barrel tip and the direction the gun points, in the world.
fn muzzle(p: &Player, tf: &Transform) -> (Vec3, Vec3) {
    let dir = Quat::from_rotation_y(p.yaw + p.gun_yaw) * (Quat::from_rotation_z(p.gun_pitch) * Vec3::X);
    (tf.translation + tf.rotation * TRUNNION + dir * BARREL, dir)
}

fn fire(
    c: Res<Controls>,
    player: Single<(&mut Player, &Transform)>,
    mut commands: Commands,
    assets: Res<AssetServer>,
) {
    let (mut p, tf) = player.into_inner();
    if !p.dived && c.shell && p.shell_cd <= 0.0 {
        p.shell_cd = 0.6;
        p.kick = 1.0;
        let (at, dir) = muzzle(&p, tf);
        shoot(&mut commands, &assets, "shell", at, Projectile { vel: dir * SHELL_SPEED, gravity: GRAVITY, ramp: 0.0, age: 0.0, life: 5.0, damage: 1 });
    }
    if c.torpedo && p.torpedo_cd <= 0.0 {
        p.torpedo_cd = 2.0;
        let forward = Quat::from_rotation_y(p.yaw) * Vec3::X;
        let at = Vec3::new(tf.translation.x, TORPEDO_DEPTH, tf.translation.z) + forward * 0.9;
        let torpedo = Projectile { vel: forward * TORPEDO_SPEED, gravity: 0.0, ramp: 1.5, age: 0.0, life: 14.0, damage: 3 };
        shoot(&mut commands, &assets, "torpedo", at, torpedo).insert(Torpedo(0.0)).observe(find_torpedo_prop);
    }
}

/// Red disc where a shell fired now would come down.
fn marker(player: Single<(&Player, &Transform)>, mut disc: Single<(&mut Transform, &mut Visibility), (With<Marker>, Without<Player>)>) {
    let (p, tf) = *player;
    let (at, dir) = muzzle(p, tf);
    let vel = dir * SHELL_SPEED;
    let t = (vel.y + (vel.y * vel.y + 2.0 * GRAVITY * at.y).sqrt()) / GRAVITY;
    disc.0.translation = Vec3::new(at.x + vel.x * t, 0.0, at.z + vel.z * t);
    *disc.1 = if p.dived { Visibility::Hidden } else { Visibility::Inherited };
}

fn boom(commands: &mut Commands, assets: &AssetServer, at: Vec3, size: f32) {
    commands.spawn((Round, Explosion { t: 0.0, size }, Transform::from_translation(at).with_scale(Vec3::ZERO), model(assets, "explosion")));
}

fn fly(
    time: Res<Time>,
    mut commands: Commands,
    assets: Res<AssetServer>,
    mut shots: Query<(Entity, &mut Projectile, &mut Transform)>,
    mut enemies: Query<(Entity, &mut Enemy, &Transform), Without<Projectile>>,
) {
    let dt = time.delta_secs();
    for (shot, mut p, mut tf) in &mut shots {
        p.age += dt;
        let speed_up = if p.ramp > 0.0 { (p.age / p.ramp).min(1.0) } else { 1.0 };
        p.vel.y -= p.gravity * dt;
        tf.translation += p.vel * speed_up * dt;
        tf.rotation = Quat::from_rotation_arc(Vec3::X, p.vel.normalize());
        let hit = enemies
            .iter_mut()
            .find(|(_, e, t)| e.hp > 0 && (t.translation + Vec3::Y * 0.15).distance(tf.translation) < HIT_RADIUS);
        if let Some((enemy, mut e, _)) = hit {
            e.hp -= p.damage;
            let dead = e.hp <= 0;
            boom(&mut commands, &assets, tf.translation, if dead { 2.0 } else { 0.7 });
            if dead {
                commands.entity(enemy).despawn();
            }
            commands.entity(shot).despawn();
        } else if p.age >= p.life || tf.translation.y < -0.4 {
            commands.entity(shot).despawn();
        }
    }
}

/// Torpedoes: a corkscrew of bubbles behind the tail, and the propeller turning.
fn trail(
    time: Res<Time>,
    look: Res<Look>,
    mut commands: Commands,
    mut torpedoes: Query<(&mut Torpedo, &Projectile, &Transform)>,
    mut props: Query<&mut Transform, (With<TorpedoProp>, Without<Torpedo>)>,
) {
    let dt = time.delta_secs();
    for (mut t, p, tf) in &mut torpedoes {
        t.0 += dt;
        if t.0 < 0.03 {
            continue;
        }
        t.0 = 0.0;
        let a = p.age * 20.0;
        let at = tf.translation + tf.rotation * Vec3::new(-0.3, a.cos() * 0.05, a.sin() * 0.05);
        commands.spawn((
            Round,
            Bubble { life: 1.0, size: 0.07 },
            Mesh3d(look.bubble.clone()),
            MeshMaterial3d(look.foam.clone()),
            Transform::from_translation(at).with_scale(Vec3::splat(0.07)),
            NotShadowCaster,
        ));
    }
    for mut tf in &mut props {
        tf.rotate_local_x(dt * 40.0);
    }
}

/// Grows fast, shrinks away, spins a little.
fn explode(time: Res<Time>, mut commands: Commands, mut booms: Query<(Entity, &mut Explosion, &mut Transform)>) {
    let dt = time.delta_secs();
    for (e, mut boom, mut tf) in &mut booms {
        boom.t += dt / 0.6;
        if boom.t >= 1.0 {
            commands.entity(e).despawn();
            continue;
        }
        tf.scale = Vec3::splat(boom.size * (4.0 * boom.t * (1.0 - boom.t)).sqrt());
        tf.rotate_y(dt * 3.0);
    }
}

fn animate(player: Single<&Player>, time: Res<Time>, mut parts: Query<(&Part, &Rest, &mut Transform)>) {
    let t = time.elapsed_secs();
    for (part, rest, mut tf) in &mut parts {
        match part {
            Part::Gun => tf.rotation = Quat::from_rotation_y(player.gun_yaw),
            Part::Barrel => tf.rotation = Quat::from_rotation_z(player.gun_pitch),
            Part::Recoil => tf.translation = rest.0 - Vec3::X * 0.06 * player.kick * player.kick,
            // Retracted into the tower when surfaced, sticking out above the water when dived.
            Part::Periscope => tf.translation = rest.0 + Vec3::Y * 0.3 * (player.depth - 1.0),
            Part::Propeller => tf.rotation = Quat::from_rotation_x(player.prop),
            Part::Rudder => tf.rotation = Quat::from_rotation_y(-player.rudder * 0.5),
            Part::Cloth(i) => tf.rotation = Quat::from_rotation_y((t * 7.0 - *i as f32 * 1.3).sin() * (0.16 + 0.05 * *i as f32)),
        }
    }
}

/// Chase camera: close behind and above the boat, looking where it is heading.
fn follow(time: Res<Time>, player: Single<(&Player, &Transform), Without<Camera3d>>, mut camera: Single<&mut Transform, With<Camera3d>>) {
    let (p, tf) = *player;
    let forward = Quat::from_rotation_y(p.yaw) * Vec3::X;
    let focus = Vec3::new(tf.translation.x, 0.0, tf.translation.z);
    let goal = focus - forward * 3.8 + Vec3::Y * 2.0;
    camera.translation = camera.translation.lerp(goal, (3.0 * time.delta_secs()).min(1.0));
    camera.look_at(focus + forward * 3.0, Vec3::Y);
}

/// Foam bubbles left behind the stern while moving.
fn wake(
    time: Res<Time>,
    look: Res<Look>,
    player: Single<(&Player, &Transform)>,
    mut since: Local<f32>,
    mut commands: Commands,
) {
    let (p, tf) = *player;
    *since += time.delta_secs();
    if *since < 0.1 || p.speed.abs() < 0.3 {
        return;
    }
    *since = 0.0;
    let at = Vec3::new(tf.translation.x, 0.0, tf.translation.z) + tf.rotation * Vec3::new(-0.95, 0.0, 0.0);
    commands.spawn((
        Round,
        Bubble { life: 1.0, size: 0.18 },
        Mesh3d(look.bubble.clone()),
        MeshMaterial3d(look.foam.clone()),
        Transform::from_translation(at).with_scale(Vec3::splat(0.18)),
        NotShadowCaster,
    ));
}

/// Bubbles drift up and shrink to nothing.
fn bubbles(time: Res<Time>, mut commands: Commands, mut all: Query<(Entity, &mut Bubble, &mut Transform)>) {
    let dt = time.delta_secs();
    for (e, mut b, mut tf) in &mut all {
        b.life -= dt;
        if b.life <= 0.0 {
            commands.entity(e).despawn();
        } else {
            tf.translation.y += dt * 0.1;
            tf.scale = Vec3::splat(b.size * b.life);
        }
    }
}

fn restart(c: Res<Controls>, round: Query<Entity, With<Round>>, mut commands: Commands, assets: Res<AssetServer>) {
    if c.restart {
        for e in &round {
            commands.entity(e).despawn();
        }
        spawn_round(&mut commands, &assets);
    }
}

fn hud(
    player: Query<&Player>,
    enemies: Query<&Enemy>,
    touch: Res<Touch>,
    window: Single<&Window>,
    mut text: Single<&mut Text, With<Hud>>,
) {
    let left = enemies.iter().count();
    let (throttle, rudder, dived) = player
        .single()
        .map_or(("", 0.0, false), |p| (THROTTLE[p.throttle].0, p.rudder, p.dived));
    let status = if left == 0 {
        if touch.on { "ALL SUNK! Tap RESTART" } else { "ALL SUNK! R = play again" }
    } else if dived {
        "PERISCOPE DEPTH: torpedoes only"
    } else {
        "surfaced"
    };
    let side = if rudder < -0.05 { "R" } else if rudder > 0.05 { "L" } else { "-" };
    let help = match (touch.on, window.width() < window.height()) {
        (true, true) => "Rotate your device to landscape\n",
        (true, false) => "",
        _ => "W/S engine (X stop)  A/D rudder (C centre)  arrows gun  SPACE shell  T torpedo  F dive  R restart\n",
    };
    text.0 = format!(
        "{help}Enemies: {left}   Engine: {throttle}   Rudder: {side} {:.0}%   {status}",
        rudder.abs() * 100.0
    );
}

fn touch_button(row: &mut ChildSpawnerCommands, label: &str, action: Action) {
    row.spawn((
        TouchButton(action),
        Node {
            width: Val::VMin(19.0),
            height: Val::VMin(12.0),
            margin: UiRect::all(Val::Px(3.0)),
            justify_content: JustifyContent::Center,
            align_items: AlignItems::Center,
            ..default()
        },
        BackgroundColor(Color::srgba(0.0, 0.0, 0.0, 0.35)),
    ))
    .with_child((Text::new(label), TextFont::from_font_size(15.0), TextColor(Color::WHITE)))
    .observe(move |_: On<Pointer<Press>>, mut touch: ResMut<Touch>| {
        touch.held.insert(action);
        touch.tapped.insert(action);
    })
    .observe(move |_: On<Pointer<Release>>, mut touch: ResMut<Touch>| {
        touch.held.remove(&action);
    })
    .observe(move |_: On<Pointer<Out>>, mut touch: ResMut<Touch>| {
        touch.held.remove(&action);
    });
}

/// A captioned column of button rows.
fn touch_panel(root: &mut ChildSpawnerCommands, rows: &[(&str, &[(&str, Action)])]) {
    root.spawn(Node { flex_direction: FlexDirection::Column, align_items: AlignItems::Center, ..default() }).with_children(|panel| {
        for (caption, buttons) in rows {
            panel.spawn((Text::new(*caption), TextFont::from_font_size(12.0), TextColor(Color::srgba(1.0, 1.0, 1.0, 0.8))));
            panel
                .spawn(Node { flex_direction: FlexDirection::Row, ..default() })
                .with_children(|row| {
                    for (label, action) in *buttons {
                        touch_button(row, label, *action);
                    }
                });
        }
    });
}

fn spawn_touch_ui(commands: &mut Commands) {
    use Action::*;
    commands
        .spawn((
            TouchRoot,
            Node {
                position_type: PositionType::Absolute,
                width: Val::Percent(100.0),
                height: Val::Percent(100.0),
                display: Display::None,
                justify_content: JustifyContent::SpaceBetween,
                align_items: AlignItems::FlexEnd,
                padding: UiRect::all(Val::Px(10.0)),
                ..default()
            },
            Pickable::IGNORE,
        ))
        .with_children(|root| {
            touch_panel(root, &[("ENGINE", &[("-", Slower), ("STOP", Stop), ("+", Faster)]), ("RUDDER", &[("<", RudderLeft), ("C", Centre), (">", RudderRight)])]);
            touch_panel(root, &[("", &[("SHELL", Shell), ("TORPEDO", Torpedo), ("DIVE", Dive)]), ("GUN", &[("<", GunLeft), ("^", GunUp), ("v", GunDown), (">", GunRight)])]);
            root.spawn((
                TouchButton(Restart),
                Node {
                    position_type: PositionType::Absolute,
                    top: Val::Px(10.0),
                    right: Val::Px(10.0),
                    padding: UiRect::all(Val::Px(8.0)),
                    ..default()
                },
                BackgroundColor(Color::srgba(0.0, 0.0, 0.0, 0.35)),
            ))
            .with_child((Text::new("RESTART"), TextFont::from_font_size(14.0), TextColor(Color::WHITE)))
            .observe(|_: On<Pointer<Press>>, mut touch: ResMut<Touch>| {
                touch.tapped.insert(Restart);
            });
        });
}

/// Shows the buttons on touch devices and lights up the ones being held.
fn touch_ui(touch: Res<Touch>, mut root: Single<&mut Node, With<TouchRoot>>, mut buttons: Query<(&TouchButton, &mut BackgroundColor)>) {
    root.display = if touch.on { Display::Flex } else { Display::None };
    for (button, mut color) in &mut buttons {
        let alpha = if touch.held.contains(&button.0) { 0.7 } else { 0.35 };
        color.0 = Color::srgba(0.0, 0.0, 0.0, alpha);
    }
}
