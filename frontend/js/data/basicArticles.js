/**
 * 基础精选阅读文章库（学生端外语学习 · 阅读理解页面 · BBC 风格）
 *
 * 内容说明：
 * - tag 区分篇幅：'BASIC'（短篇阅读 10 篇）/ 'BASIC-LONG'（长篇阅读 10 篇）
 * - 风格参考 BBC News：现在时主动语态标题、短段落、事实归因
 *   （researchers say / according to / told the BBC）、中性客观语气
 * - 篇幅：短篇 90~170 词，长篇 200~330 词
 * - 难度映射：A2/B1（短篇），B1/B2（长篇）
 * - 题材：科学 / 自然 / 环境 / 文化 / 心理 / 教育 / 太空 / 历史 等
 * - theme 字段标注题材，便于教学检索
 */

export const BASIC_SHORT_ARTICLES = [
    {
        id: 'basic-mudskipper',
        title: 'The Fish That Climb Trees',
        tag: 'BASIC',
        level: 'B1',
        theme: '自然·动物适应（BBC 风格）',
        text: `Mudskippers look like ordinary fish, but they spend most of their lives out of the water. These unusual creatures live in mangrove forests, where they climb tree roots and even jump across mud at surprising speed.

Scientists say mudskippers can breathe through their skin and the lining of their mouths, as long as they stay damp. Their strong front fins work like little arms, helping them pull themselves upwards.

Researchers studying the fish in Southeast Asia say their climbing skills may have developed to escape rising tides and hungry predators in the water.

'They are living proof of how life can adapt to the strangest places,' one biologist told the BBC.`
    },
    {
        id: 'basic-phonebox',
        title: 'A Second Life for the Red Phone Box',
        tag: 'BASIC',
        level: 'B1',
        theme: '文化·英国电话亭改造（BBC 风格）',
        text: `More than sixty years ago, the red telephone box was a familiar sight on almost every British street. Today, with most people carrying mobiles, the famous boxes have become empty and silent.

But instead of removing them, some communities are finding new uses. Hundreds of the red boxes now serve as tiny libraries, where neighbours borrow and return books for free. Others have been turned into coffee stands, art galleries and even first-aid points with defibrillators.

'People love them because they are part of our history,' says one volunteer who runs a library box in a small village.

Telecoms companies now allow councils to adopt unused boxes for just one pound. The scheme has saved thousands from the scrapyard, and new ideas keep arriving.`
    },
    {
        id: 'basic-cartown',
        title: 'The Town That Banned Cars',
        tag: 'BASIC',
        level: 'B1',
        theme: '城市·无车小镇（BBC 风格）',
        text: `In the centre of Pontevedra, a small city in northern Spain, cars are not welcome. Fifteen years ago, local leaders decided to ban traffic from the main streets and give the space back to people.

The change was dramatic. Air pollution fell, noise disappeared, and residents began walking to work and school. Children now play safely in squares that were once car parks.

According to the city council, the number of shops has grown and more families are moving back into the centre. Some drivers complained at first, but today most residents support the policy.

'We did not invent anything new,' the mayor told the BBC. 'We simply remembered that cities are for people, not for cars.'`
    },
    {
        id: 'basic-yawn',
        title: 'Why Do We Yawn?',
        tag: 'BASIC',
        level: 'A2',
        theme: '科学·打哈欠之谜（BBC 风格）',
        text: `You see someone yawn, and suddenly you want to yawn too. But why do we do it?

For years, scientists believed yawning was a sign of tiredness or boredom. Some experts still think it cools the brain and helps us stay alert. However, the true answer is still unknown.

One thing is clear: yawning is contagious. Even dogs can catch a yawn from their owners. Researchers say the behaviour may have developed to help groups of animals stay in rhythm, waking and sleeping together.

So the next time you yawn in class, do not worry. Your brain may simply be doing its job — and your friends will probably join you.`
    },
    {
        id: 'basic-dolphin-name',
        title: 'Dolphins Call Each Other by Name',
        tag: 'BASIC',
        level: 'B1',
        theme: '动物·海豚签名哨声（BBC 风格）',
        text: `Every dolphin has its own special whistle, something like a name. When dolphins meet after a long time apart, they call out these sounds to greet one another.

Scientists at the University of St Andrews have studied these signature whistles for years. In a recent experiment, they played recorded calls to wild dolphins and watched their reactions. The animals responded most strongly when they heard their own whistle.

The researchers say dolphins copy the whistle of a close friend, and the friend replies with the same sound — a conversation that looks remarkably human.

'This is the first time we have seen animals address each other in this way,' one of the scientists told the BBC.`
    },
    {
        id: 'basic-bottle',
        title: 'The Oldest Message in a Bottle',
        tag: 'BASIC',
        level: 'B1',
        theme: '历史·漂流瓶（BBC 风格）',
        text: `In 2018, a woman walking on a beach in Western Australia found a glass bottle buried in the sand. Inside was a message, written in German and dated 12 June 1886.

Researchers checked the name and address on the paper and confirmed the story. The bottle had been thrown from a ship more than 130 years earlier, as part of a scientific experiment to study ocean currents.

The message asked anyone who found it to report the location. It is now believed to be the oldest message in a bottle ever discovered.

'I almost dropped it when I saw the date,' the woman told reporters. The bottle had travelled more than 20,000 kilometres around the world before reaching her hands.`
    },
    {
        id: 'basic-woodweb',
        title: 'The Wood Wide Web',
        tag: 'BASIC',
        level: 'B2',
        theme: '自然·树木地下网络（BBC 风格）',
        text: `Trees may look independent, but scientists say they are connected by an underground network of fungi. This hidden system has been nicknamed the 'wood wide web'.

Through the fungi, trees can share water, sugar and chemical signals. When one tree is attacked by insects, it can warn its neighbours, which then produce defensive chemicals. Older trees even appear to feed younger seedlings growing in the shade.

Dr Suzanne Simard, a forest ecologist in Canada, discovered this behaviour in the 1990s. Her experiments showed that paper birch and Douglas fir trees were trading carbon through the network.

Experts say the findings change how we should manage forests. Cutting down an old tree, they argue, may hurt more than the tree itself — it could break an entire community.`
    },
    {
        id: 'basic-cubesat',
        title: 'Tiny Satellites, Big Science',
        tag: 'BASIC',
        level: 'B1',
        theme: '太空·立方星（BBC 风格）',
        text: `For decades, space exploration meant huge satellites that cost millions of dollars and took years to build. Today, a new kind of spacecraft is changing the rules.

CubeSats are small satellites the size of a shoebox. They are cheap, quick to build, and often launched in groups of dozens at a time. Universities, schools and even individual companies now send their own experiments into orbit.

According to space agencies, these tiny satellites can monitor weather, watch crops and track ships at sea. They can also test new technology before it is used on bigger missions.

One engineer told the BBC that the devices have 'opened the door of space to everyone'. The small satellites, it seems, are having a very big impact.`
    },
    {
        id: 'basic-bee-goal',
        title: 'Bees Learn to Play Football',
        tag: 'BASIC',
        level: 'A2',
        theme: '科学·蜜蜂学习实验（BBC 风格）',
        text: `Scientists in London have taught bees to play football — well, almost.

In the experiment, the insects had to push a small ball into a goal to receive sugar water. At first, none of the bees knew what to do. But after watching another bee score, most of them quickly learned the trick.

The team at Queen Mary University says the result shows bees are smarter than many people think. They can copy the behaviour of others and remember it days later.

'Bees have tiny brains, but they can learn complicated tasks,' one researcher told the BBC. 'We should respect them a lot more.'

The insects have not yet asked for match fees.`
    },
    {
        id: 'basic-handwrite',
        title: 'Why Handwritten Notes Beat Typing',
        tag: 'BASIC',
        level: 'B1',
        theme: '教育·手写笔记（BBC 风格）',
        text: `Laptops are faster than pens, so students who type usually write down more words. But researchers say those who take notes by hand may actually learn more.

In a study by Princeton University, students who typed copied almost everything their teacher said, word for word. Students who wrote by hand could not keep up, so they had to summarise the ideas in their own words.

According to the researchers, this process of thinking and rewriting is what helps the brain remember. Typing, they argue, is too easy and demands little thinking.

The advice may sound old-fashioned, but the science is clear: for studying, sometimes the slowest tool is the smartest one.`
    }
];

export const BASIC_LONG_ARTICLES = [
    {
        id: 'basic-reef',
        title: 'New Hope for the Great Barrier Reef',
        tag: 'BASIC-LONG',
        level: 'B2',
        theme: '环境·大堡礁修复（BBC 风格）',
        text: `Australia's Great Barrier Reef is the largest living structure on Earth, stretching more than 2,300 kilometres along the coast of Queensland. It is home to thousands of species of fish, corals and turtles. But in recent years, rising sea temperatures have turned large areas of the reef white, a process known as bleaching.

When the water gets too warm, corals lose the tiny algae that give them their colour and most of their food. If temperatures fall quickly, the corals can recover. If not, they starve and die. Scientists say the reef has suffered three serious bleaching events in the last five years.

Now, a new generation of scientists is fighting back. In underwater nurseries, researchers grow young corals in protected frames, then plant them on damaged parts of the reef. Some of these restored corals have survived and are already reproducing.

Dr Emma Camp, a marine biologist leading part of the work, told the BBC that the results give her genuine hope. But she warns that planting corals alone cannot solve the problem.

'The reef needs cooler water, and that means cutting greenhouse gas emissions around the world,' she said. 'Restoration buys us time, but it is not a cure.'

Experts agree that the reef is not lost yet. Its recovery, they say, depends on decisions made far from the ocean — in boardrooms and parliament buildings.`
    },
    {
        id: 'basic-heatcity',
        title: 'Why Cities Are Getting Hotter',
        tag: 'BASIC-LONG',
        level: 'B1',
        theme: '环境·城市热岛（BBC 风格）',
        text: `Cities have always been warmer than the countryside around them. Concrete, roads and buildings absorb the sun's heat during the day and release it slowly at night. Scientists call this the urban heat island effect, and it is getting worse.

Climate change has pushed global temperatures up. But in many cities, the heat is rising twice as fast as in rural areas. During heatwaves, the temperature in a city centre can be several degrees higher than in nearby fields.

The result is not just discomfort. Heat is dangerous, especially for older people and small children. Health officials in Europe say last summer's heatwaves were linked to thousands of extra deaths.

Planners say the answer is to make cities greener. Trees give shade and cool the air when water evaporates from their leaves. Pale-coloured roofs and roads reflect sunlight instead of absorbing it. Green spaces, ponds and fountains all help.

Some cities are already leading the way. Paris has created cool islands in public parks, and Melbourne has planted thousands of trees along its streets.

'Every degree matters,' one climate scientist told the BBC. 'We cannot cool the whole planet from one city, but we can make our cities safer for the people who live in them.'`
    },
    {
        id: 'basic-verticalfarm',
        title: 'The Rise of Vertical Farms',
        tag: 'BASIC-LONG',
        level: 'B2',
        theme: '农业·垂直农场（BBC 风格）',
        text: `Imagine a farm that grows lettuce on shelves stacked twenty layers high, in the middle of a city, with no soil and no sunlight. That is the idea behind vertical farming, one of the fastest-growing trends in agriculture.

In these farms, plants grow indoors under LED lights, with their roots in water enriched with nutrients. Sensors control the temperature, humidity and light exactly. Nothing is wasted: the water is recycled, and there are no pests, which means no pesticides.

Supporters say the system has clear advantages. It uses about 95 percent less water than traditional farming. Crops can be harvested all year round, and because the farms sit close to cities, vegetables arrive fresh within hours instead of days.

Critics, however, point to one big problem: energy. The LED lights and climate control need huge amounts of electricity, which often comes from fossil fuels. Some researchers argue that, in sunny countries, growing outdoors is still greener.

The industry is responding. New farms are powered partly by solar panels, and scientists are developing more efficient lights. As prices fall, vertical farms are moving beyond luxury salads into everyday food.

Whether they will ever replace traditional fields is doubtful. But as the world's population grows, experts say, cities will need every way of growing food they can find.`
    },
    {
        id: 'basic-memory',
        title: 'Can We Really Trust Our Memories?',
        tag: 'BASIC-LONG',
        level: 'B2',
        theme: '心理·记忆与目击证词（BBC 风格）',
        text: `Most of us believe our memories are like recordings — accurate, unchangeable pictures of the past. Psychologists say the truth is very different. Every time we remember something, we rebuild it, and each rebuild can change the original.

Dr Elizabeth Loftus, a memory researcher at the University of California, has spent decades proving this. In one famous experiment, she showed people a video of a car accident and then asked different questions about it. The wording of the questions changed what the witnesses reported — and what they believed they had seen.

Even more surprising, memories can be created entirely. In another study, participants were told that they had been lost in a shopping centre as children, a story that was completely false. A quarter of them later described the memory in detail, adding events that had never happened.

This is not just an academic question. In courtrooms, eyewitness evidence is still treated as powerful proof, although research shows it is often unreliable. Police in several countries now change the way they interview witnesses to avoid putting ideas into their minds.

Does this mean our memories are useless? Not at all. They help us learn, connect with others and build our identity. But they are built for meaning, not for perfect accuracy.

'Memory is not a copy of the past,' Dr Loftus told the BBC. 'It is a story we tell ourselves — and stories can change.'`
    },
    {
        id: 'basic-ai-classroom',
        title: 'The Quiet Revolution of AI in the Classroom',
        tag: 'BASIC-LONG',
        level: 'B2',
        theme: '教育·自适应学习（BBC 风格）',
        text: `Walk into a modern classroom and you may see something unexpected: students working on tablets while a computer programme decides which maths questions each one should answer next. This is adaptive learning, and it is quietly changing education.

The idea is simple. The software watches every answer a student gives. If the student answers correctly, the programme makes the questions slightly harder. If the student struggles, it goes back and explains the basics again. In this way, every pupil gets a personal path through the subject.

Teachers say the technology has one clear advantage: time. While the computer handles routine practice, the teacher can spend more time with students who need extra help.

But experts warn that the revolution has limits. A machine can see that a student is failing, but it cannot see why — perhaps the child is hungry, tired or afraid to ask questions. Education, they argue, is as much about relationships as information.

There are also worries about privacy. Schools now collect detailed data on every pupil, and some parents ask who owns that information and how long it is kept.

Supporters admit the problems but point to the results. In trials, schools using adaptive software showed faster progress in maths than those that did not.

'Technology will not replace teachers,' one head teacher told the BBC. 'But teachers who use technology well will replace those who do not.'`
    },
    {
        id: 'basic-antarctica',
        title: 'Antarctica: The Continent That Shapes Our Climate',
        tag: 'BASIC-LONG',
        level: 'B2',
        theme: '地理·南极与海平面（BBC 风格）',
        text: `Antarctica is the coldest, driest and windiest place on Earth. It is a continent of ice, almost completely covered by a sheet that is, in places, four kilometres thick. Yet this frozen desert plays a huge role in the climate of the whole planet.

The white ice reflects most of the sun's energy back into space, helping to keep the Earth cool. Scientists call this the albedo effect. The ocean around Antarctica also absorbs enormous amounts of heat and carbon dioxide from the atmosphere.

In recent years, however, the continent has been changing. Researchers have measured warming waters beneath the floating ice shelves, the giant platforms where glaciers meet the sea. When these shelves thin or break, the glaciers behind them slide faster into the ocean.

If all of Antarctica's ice melted, sea levels would rise by about 58 metres. No scientist expects that to happen soon. But even a small loss is important: a rise of just one metre would threaten coastal cities from Shanghai to Miami, where hundreds of millions of people live.

The good news is that Antarctica is not melting everywhere. Parts of East Antarctica are actually gaining ice, and scientists say the picture is more complex than simple headlines suggest.

Still, experts agree on the direction of change. The continent is losing ice, and the pace is quickening. As one glaciologist told the BBC: 'Antarctica is not a distant problem. Its ice is connected to every coastline on Earth.'`
    },
    {
        id: 'basic-horror',
        title: 'Why Do We Love Horror Films?',
        tag: 'BASIC-LONG',
        level: 'B1',
        theme: '心理·恐怖片心理学（BBC 风格）',
        text: `Millions of people pay good money to be terrified. Horror films fill cinemas every year, and their fans watch them again and again. But if fear is so unpleasant, why do we enjoy it?

Scientists say the answer lies in the difference between real fear and film fear. In a cinema, your brain sends out alarm signals — your heart beats faster and your palms sweat — but another part of your brain knows you are safe. This mixture of danger and safety creates excitement, not panic.

Some researchers believe horror films offer more than thrills. Watching a scary story lets people practise dealing with difficult situations without real risk. It is a kind of rehearsal for life's dangers, from storms to strangers.

There may also be a social reason. Studies show that watching horror together brings people closer. When we are afraid, our brains release chemicals that strengthen bonds with those around us.

Not everyone is a fan, of course. Psychologists say people who enjoy horror often score high on curiosity and low on fearfulness. They simply react to the same film in a different way.

So the next time a friend drags you to a scary movie, you can relax. Your heartbeat may say danger, but your brain knows the truth — it is only a story.`
    },
    {
        id: 'basic-bee-dance',
        title: 'The Dance That Tells Bees Where to Go',
        tag: 'BASIC-LONG',
        level: 'B1',
        theme: '科学·蜜蜂摇摆舞（BBC 风格）',
        text: `Honeybees cannot talk, but they can dance — and their dance is one of the most remarkable communication systems in nature. When a worker bee finds a rich patch of flowers, it returns to the hive and performs a special movement called the waggle dance.

The dance looks like a figure of eight. In the middle of the dance, the bee shakes its body and moves in a straight line. The angle of that line tells the other bees the direction of the flowers, compared with the sun. The length of the dance tells them the distance.

For centuries, people believed bees simply flew around randomly. It took a scientist called Karl von Frisch to decode the dance, a discovery that won him the Nobel Prize in 1966.

Later research added another detail: bees use the sun, but they can also navigate on cloudy days by reading the polarisation of light in the sky. Even more impressive, the hive works like a living brain, with thousands of workers sharing small pieces of information.

Scientists are still finding new layers of meaning in the dance. The quality of the flowers, the danger from predators and even the time of day all seem to change the message.

'It is the only known language in nature that can talk about things that are not present,' one researcher told the BBC. 'Bees describe a field of flowers they have never seen.'

Understanding the dance is not just curiosity. Farmers and conservationists hope that listening to bees will help protect them — and the crops they pollinate.`
    },
    {
        id: 'basic-plastic',
        title: 'What Happens to Your Plastic Bottle?',
        tag: 'BASIC-LONG',
        level: 'B1',
        theme: '环境·塑料瓶去向（BBC 风格）',
        text: `You finish a bottle of water, throw it in the recycling bin, and probably never think about it again. But the journey of that bottle is longer and stranger than you might imagine.

In many countries, the bottle is collected, washed and melted down to make new plastic products. This sounds good, but the reality is more complicated. Recycling plastic is expensive, and every time it is melted, its quality drops. After a few cycles, it can no longer be used for food packaging at all.

Some of the bottles that are not recycled end up in landfill, where they can survive for hundreds of years. Others find their way into rivers and oceans. Scientists estimate that more than eight million tonnes of plastic enter the sea every year, and bottles are one of the most common items found on beaches.

The problem has grown faster than the solution. In the 1950s, the world produced about two million tonnes of plastic a year. Today the figure is more than 400 million tonnes, and only a small fraction is truly recycled.

Some countries are taking bold steps. Several European nations now charge customers for plastic bottles, and the number of bottles returned for recycling has risen sharply. Companies are also designing lighter bottles and using more recycled material.

Environmental groups say the answer is simple in theory: use less plastic, and design products that can be reused again and again. As one campaigner told the BBC, 'The best bottle is the one you use a hundred times.'`
    },
    {
        id: 'basic-europa',
        title: 'Searching for Life on Europa',
        tag: 'BASIC-LONG',
        level: 'B2',
        theme: '太空·木卫二生命搜寻（BBC 风格）',
        text: `One of the most exciting questions in science is whether life exists beyond Earth. In our own solar system, many researchers believe the best place to look is not Mars, but a small moon of Jupiter called Europa.

Europa is covered in a thick layer of ice. But beneath that ice, scientists are almost certain there is a vast ocean of liquid water, containing twice as much water as all of Earth's oceans put together. The moon is constantly squeezed by Jupiter's gravity, which heats its interior and keeps the water liquid.

Where there is water, there may be life. On Earth, scientists have found living creatures in the deepest, darkest parts of the ocean, near volcanic vents that provide heat and food. If life can survive there, they argue, it might also survive in Europa's dark ocean.

NASA is now preparing a mission called Europa Clipper, which will fly past the moon dozens of times, mapping its surface and studying the chemistry of the ice. The spacecraft is not designed to find life directly, but it will look for the conditions life needs.

The mission will not land, and its answers may only raise more questions. Yet scientists say the search itself is valuable.

'We are looking for a second genesis,' one planetary scientist told the BBC. 'If we find life there, it means life is common in the universe. If we do not, we learn how special our own planet is.'

Either way, the frozen moon may rewrite our understanding of where life can exist.`
    }
];
