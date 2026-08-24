/**
 * 口语跟读训练文章库（学生端外语学习 · 口语训练 · READ ALOUD 跟读）
 *
 * 内容说明：
 * - tier 区分三个训练等级：'beginner'（入门 10 篇）/ 'intermediate'（中等 10 篇）/ 'advanced'（进阶 10 篇）
 * - 全部 30 篇选题经联网调研，基于真实新闻报道与权威机构公开内容
 *   （BBC News / BBC Future / BBC Earth / The Guardian / National Geographic /
 *   UNESCO / UNEP / WHO / NASA / IEA / Copernicus / Nature Medicine 等），
 *   按 BBC 新闻风格用自己的语言重新组织（保留真实事实与数字，不复制原文句子）
 * - 篇幅：入门 60~100 词（A1-A2），中等 100~150 词（B1-B2），进阶 120~180 词（B2-C1）
 * - source 字段标注素材来源，theme 字段标注题材，便于教学检索
 */

export const SPEAKING_TIERS = [
    { id: 'beginner', label: '入门', en: 'BEGINNER', cefr: 'A1-A2', note: '简单句 · 基础词汇 · 60~100 词' },
    { id: 'intermediate', label: '中等', en: 'INTERMEDIATE', cefr: 'B1-B2', note: '常见从句 · 热点新闻 · 100~150 词' },
    { id: 'advanced', label: '进阶', en: 'ADVANCED', cefr: 'B2-C1', note: '抽象论述 · 长难句 · 120~180 词' }
];

export const SPEAKING_ARTICLES = [
    // ==================== 入门 BEGINNER ====================
    {
        id: 'spk-coffee',
        tier: 'beginner',
        title: 'Why Coffee Wakes You Up',
        cefr: 'A2',
        theme: '健康·咖啡因提神原理',
        source: 'BBC Future',
        text: `Coffee wakes millions of people every morning, but how? Inside your brain, a chemical called adenosine slowly builds up all day. It makes you feel sleepy. Caffeine is clever: it blocks the place where adenosine works. Your brain never gets the "tired" message, so you stay alert. The effect starts about 45 minutes after your first sip. Scientists say four cups a day is usually safe for healthy adults. Too much coffee, however, can keep you awake at night.`
    },
    {
        id: 'spk-bee-dance',
        tier: 'beginner',
        title: 'The Dance That Guides Bees to Flowers',
        cefr: 'A2',
        theme: '动物·蜜蜂摇摆舞交流',
        source: 'BBC Earth',
        text: `Bees are famous for their hard work, but they are also excellent dancers. A honeybee that finds flowers flies home and performs a special dance. The dance tells other bees where the food is. The angle of the dance shows the direction of the sun, and the longer the dance, the farther the flowers. A scientist called Karl von Frisch spent years studying this "language" of bees. In 1973, his discovery won a Nobel Prize. Next time you see a bee, remember: it may be sharing directions.`
    },
    {
        id: 'spk-dog-tail',
        tier: 'beginner',
        title: 'Why Do Dogs Wag Their Tails?',
        cefr: 'A2',
        theme: '动物·狗尾巴的社交信号',
        source: 'National Geographic',
        text: `Dogs cannot speak, but their tails say a lot. A dog that wags its tail to the right is usually relaxed and happy. A tail that moves to the left often means the dog is nervous or unsure. A fast, wide wag shows excitement, while a tail held low and still may mean fear. Scientists at the University of Trento in Italy discovered the left-right difference in 2007. Trainers say we should watch the whole body, not just the tail. A wagging tail is a friendly hello — but not always.`
    },
    {
        id: 'spk-qr-code',
        tier: 'beginner',
        title: 'The Tiny Square That Changed the World',
        cefr: 'A2',
        theme: '科技·二维码的诞生',
        source: 'BBC News',
        text: `Look at almost any menu or shop window today, and you will see a small black-and-white square. It is called a QR code. A Japanese engineer, Masahiro Hara, invented it in 1994. He worked for a car parts company and needed a fast way to track parts. The design came from a game of Go, with its grid of small squares. A QR code can hold about 7,000 numbers. Today people scan them to pay, to read menus, and to join Wi-Fi networks. A small square, but a giant change.`
    },
    {
        id: 'spk-emoji',
        tier: 'beginner',
        title: 'How Emoji Became a World Language',
        cefr: 'A2',
        theme: '文化·表情符号全球化',
        source: 'BBC News',
        text: `Emoji are tiny pictures that we send in messages every day. The laughing-crying face is the most used emoji in the world, and in 2015, Oxford Dictionaries even named it the Word of the Year. Every year on 17 July, people celebrate World Emoji Day. The date comes from the calendar icon, which always shows that day. There are now nearly 4,000 emoji, and the list keeps growing. Emoji help us show feelings that words cannot carry. They have truly become a global language.`
    },
    {
        id: 'spk-panda',
        tier: 'beginner',
        title: 'Pandas: A Conservation Success Story',
        cefr: 'A2',
        theme: '自然·大熊猫保护成果',
        source: 'BBC News',
        text: `Giant pandas were once one of the most endangered animals on Earth. Years of careful protection changed that story. In 2021, China announced that wild pandas were no longer endangered. Today about 1,900 pandas live in the wild, and hundreds more live in reserves. The country also built a national park for pandas that is about three times bigger than Yellowstone. Protecting bamboo forests and stopping illegal hunting made the difference. The panda shows that people can help a species return from the edge.`
    },
    {
        id: 'spk-octopus',
        tier: 'beginner',
        title: 'The Octopus: Three Hearts and Blue Blood',
        cefr: 'A2',
        theme: '自然·章鱼的奇妙身体',
        source: 'National Geographic',
        text: `The octopus is one of the strangest animals in the sea. It has eight arms covered with suckers, and it can change colour in less than a second. Even stranger: it has three hearts and blue blood. Its blood contains copper, which makes it blue. Most of the octopus's brain power is in its arms, which can taste and touch. Some octopuses can even copy the shape of dangerous animals like sea snakes. Scientists say the octopus is one of the smartest creatures without a backbone.`
    },
    {
        id: 'spk-blue-sky',
        tier: 'beginner',
        title: 'Why Is the Sky Blue?',
        cefr: 'A1',
        theme: '科学·天空颜色的光学原理',
        source: 'NASA',
        text: `Why is the sky blue and not green or red? The answer is light and air. Sunlight looks white, but it is made of many colours. When sunlight hits the air, the small gas molecules scatter the colours. Blue light scatters the most, so we see a blue sky. At sunset, the sun's light travels through more air. Blue light gets scattered away, and the red and orange light reaches our eyes. That is why sunsets look warm and golden.`
    },
    {
        id: 'spk-spring-festival',
        tier: 'beginner',
        title: 'Spring Festival Joins a World Heritage List',
        cefr: 'A2',
        theme: '文化·春节入选非遗名录',
        source: 'UNESCO',
        text: `The Spring Festival is the most important holiday in China. Families travel home, share big dinners, and light fireworks. In December 2024, UNESCO added the festival to its list of intangible cultural heritage. This list protects traditions that are important to world culture. About two billion people celebrate the Spring Festival every year, from China to communities around the world. UNESCO's decision shows how much the world values this ancient celebration. The new year of 2025 was the Year of the Snake.`
    },
    {
        id: 'spk-eclipse',
        tier: 'beginner',
        title: 'A Once-in-a-Lifetime Eclipse Wows Europe',
        cefr: 'A2',
        theme: '天文·2026 欧洲日食',
        source: 'BBC News',
        text: `On 12 August 2026, the sky went dark across parts of Europe. A solar eclipse crossed the continent, and millions of people looked up to watch. In Cornwall, England, the Moon covered about 95 percent of the Sun. In parts of Spain, the Sun disappeared completely for a few minutes. Crowds cheered as daylight turned into twilight. Such a total eclipse will not cross Europe again until the 2040s. For many people, it was a once-in-a-lifetime view — and a perfect reason to study the sky.`
    },

    // ==================== 中等 INTERMEDIATE ====================
    {
        id: 'spk-ai-classroom',
        tier: 'intermediate',
        title: 'AI Enters the Classroom: Help or Hype?',
        cefr: 'B1',
        theme: '教育·生成式 AI 进课堂',
        source: 'UNESCO / BBC',
        text: `Artificial intelligence is moving into classrooms around the world, but schools are not sure how fast to follow. In 2023, UNESCO published the first global guidance on generative AI in education. The agency advised that children under thirteen should not use generative tools, and that teachers need proper training first. Its survey found that fewer than ten percent of schools had official rules about AI at the time. Some countries are moving ahead anyway: South Korea introduced AI-powered digital textbooks in selected grades from 2025. Supporters say AI can personalise learning for every student. Critics warn that rushed adoption may widen gaps between schools. The question is not whether AI will enter education, but how carefully we let it in.`
    },
    {
        id: 'spk-plastic-treaty',
        tier: 'intermediate',
        title: 'Plastic Treaty Talks Stall Again',
        cefr: 'B2',
        theme: '环境·全球塑料条约谈判',
        source: 'BBC News / UNEP',
        text: `The world has been trying to agree on a plastics treaty for years, and negotiators still cannot find common ground. In November 2024, talks in Busan, South Korea, ended without a deal. A second round in Geneva in 2025 also failed. The main argument is simple: should the treaty limit how much plastic companies can produce? A coalition of about seventy-five countries says yes, because recycling alone cannot solve the crisis. Oil-producing nations disagree, because plastic is made from oil. Inger Andersen, the head of the UN environment programme, said the parties need time to rebuild trust. Meanwhile, plastic waste keeps growing on beaches, in rivers, and inside our food chains. Time, however, is a luxury the ocean does not have.`
    },
    {
        id: 'spk-sleep-science',
        tier: 'intermediate',
        title: 'The Science of Sleep',
        cefr: 'B1',
        theme: '健康·睡眠科学与蓝光迷思',
        source: 'BBC Future',
        text: `Nearly one in three adults does not get enough sleep, according to the US health agency CDC. Adults need about seven to nine hours a night, yet many people sleep far less. The effects are serious: poor sleep is linked to weight gain, heart problems, and weaker concentration. Scientists have also questioned popular advice about screens. The idea that blue light alone ruins sleep is more complicated than it sounds, and researchers now say the real problem is often that people simply go to bed too late. One simple fix works surprisingly well: a weekend of camping. Natural daylight helps reset the body clock, so you feel sleepy at the right time. Whatever the reason, sleep experts agree on one thing — good sleep is not a luxury, it is a health need.`
    },
    {
        id: 'spk-heat-island',
        tier: 'intermediate',
        title: 'Why Cities Are Hotter Than the Countryside',
        cefr: 'B1',
        theme: '气候·城市热岛与冷屋顶',
        source: 'Scientific American',
        text: `Walk from a leafy park into a city centre on a hot day, and you will feel the difference immediately. Cities are often several degrees warmer than the countryside around them. Concrete and asphalt absorb the sun's heat during the day and release it slowly at night. Scientists call this the urban heat island effect. A study by University College London in 2024 tested three ways to cool the capital. Reflective white roofs worked best, lowering average temperatures by more than one degree during a heatwave — about twice as effective as solar panels and four times better than trees alone. The finding matters because more than half of the world's people now live in cities. As heatwaves become more common, painting roofs white may be one of the cheapest climate tools we have.`
    },
    {
        id: 'spk-high-seas',
        tier: 'intermediate',
        title: 'A New Treaty for the High Seas',
        cefr: 'B2',
        theme: '海洋·公海条约正式生效',
        source: 'BBC News',
        text: `For the first time in history, the international waters that cover nearly two-thirds of the ocean now have a legal framework. The High Seas Treaty, agreed after years of negotiation, officially entered into force in January 2026, when Morocco became the sixtieth country to ratify it. The treaty supports the "30 by 30" goal: protecting thirty percent of the world's ocean by 2030. It also creates rules for sharing marine life discoveries and for checking the environmental impact of deep-sea activities. Greenpeace called the moment "the biggest win for ocean protection in history". Scientists hope the treaty will finally slow the damage to marine life beyond national borders, where no single country has full authority.`
    },
    {
        id: 'spk-food-waste',
        tier: 'intermediate',
        title: 'A Billion Meals in the Bin',
        cefr: 'B1',
        theme: '环境·全球食物浪费数据',
        source: 'UNEP',
        text: `The world throws away more food than many countries produce. According to the UN Environment Programme, about 1.05 billion tonnes of food went to waste in 2022 — roughly one-fifth of all food available to people. That is about 132 kilograms for every person on the planet. Most of the waste, around sixty percent, comes from home kitchens, not restaurants or shops. Besides the obvious cost, wasted food has a hidden price: when it rots in landfill, it releases gases that heat the planet. Food waste is responsible for about eight to ten percent of global greenhouse emissions. Experts say simple habits help — planning meals, buying only what we need, and using leftovers. Small changes in every kitchen add up to a very large difference.`
    },
    {
        id: 'spk-ev-record',
        tier: 'intermediate',
        title: 'Electric Cars Hit a New Record',
        cefr: 'B1',
        theme: '科技·电动汽车销量新高',
        source: 'IEA',
        text: `The electric car is no longer a niche product. Global sales of electric vehicles reached about seventeen million in 2024, making up more than one in five new cars sold. In 2025, sales passed twenty million for the first time. China leads the market: nearly half of all new cars sold there in 2024 were electric or plug-in hybrid. Norway is the most enthusiastic country of all, where more than nine out of ten new cars are now electric. Falling battery prices are the main reason for the boom, according to the International Energy Agency. Ten years ago, an electric car was a luxury choice. Today it is often the cheaper choice — and governments are betting that the trend will only accelerate.`
    },
    {
        id: 'spk-measles',
        tier: 'intermediate',
        title: 'Measles Makes a Comeback',
        cefr: 'B2',
        theme: '健康·麻疹疫情与疫苗',
        source: 'WHO / BBC',
        text: `Measles is one of the most contagious diseases in the world, and it is returning to places that had nearly forgotten it. In 2025, the United States suffered its worst outbreak in more than a decade. Health officials reported over two thousand cases across forty-four states, centred on Gaines County, Texas. Most of the people who fell seriously ill had not been vaccinated. Three people died, including a six-year-old child — the first measles death in the United States since 2015. The World Health Organization also warned of a sharp rise in Europe. The science is clear: two doses of the vaccine are about 97 percent effective. Public health experts say the outbreak is not a failure of medicine, but a reminder of what happens when vaccination rates fall.`
    },
    {
        id: 'spk-whales-arctic',
        tier: 'intermediate',
        title: 'Whales Move North as Arctic Ice Disappears',
        cefr: 'B1',
        theme: '气候·鲸群北迁格陵兰',
        source: 'BBC News',
        text: `Something is changing in the waters around Greenland. As climate change shrinks the sea ice, large whales are moving into new areas to feed — and scientists are watching "feeding frenzies" that were rarely seen before. The disappearance of ice has opened routes that were once blocked for much of the year, allowing whales to travel farther north. Researchers say this brings both opportunity and danger. More open water means new feeding grounds, but it also means more ships, more noise, and a higher risk of collisions. Marine biologists are now tracking the whales' movements to understand how the Arctic's new visitors will reshape the ecosystem. The whales are adapting to a warmer planet; the question is whether the rest of the Arctic can keep up.`
    },
    {
        id: 'spk-greenland-shark',
        tier: 'intermediate',
        title: 'The Shark That Lives for 400 Years',
        cefr: 'B1',
        theme: '自然·格陵兰鲨长寿之谜',
        source: 'BBC Future',
        text: `Somewhere in the cold waters of the North Atlantic, a shark is swimming that may have been born before Shakespeare wrote his plays. The Greenland shark is the longest-living vertebrate known to science, with a lifespan of up to four hundred years. It grows incredibly slowly — about one centimetre a year — and does not reach adulthood until around 150. Scientists use the lenses of the sharks' eyes to estimate their age, since the tissue keeps growing throughout life. In 2026, researchers began mapping the Greenland shark's genome, hoping to understand how its cells resist ageing for so long. If they can unlock the secret, the slow old shark of the deep could teach humans something remarkable about living longer.`
    },

    // ==================== 进阶 ADVANCED ====================
    {
        id: 'spk-ai-copyright',
        tier: 'advanced',
        title: 'Who Owns the Words an AI Learns From?',
        cefr: 'C1',
        theme: '科技·AI 训练数据版权之争',
        source: 'BBC News',
        text: `In December 2023, The New York Times filed a lawsuit against OpenAI and Microsoft, claiming that millions of its copyrighted articles had been used to train ChatGPT without permission. The newspaper demanded up to 150,000 dollars per work and asked the court to order the deletion of the models. It was not alone: the Authors Guild, John Grisham and Jodi Picoult were among those who followed with their own claims. The central question is whether training AI on copyrighted text counts as fair use — a legal idea that allows limited copying for purposes such as criticism or research — or simply as large-scale theft. Technology companies argue that learning from public text is no different from a human reading books. Writers reply that no human could absorb millions of works in an afternoon. The courts' answer will shape not only AI companies, but the future economics of writing itself.`
    },
    {
        id: 'spk-cop29',
        tier: 'advanced',
        title: 'COP29: The $300 Billion Promise',
        cefr: 'C1',
        theme: '气候·COP29 气候资金之争',
        source: 'BBC News',
        text: `The annual climate summit ended in Baku in November 2024 with a number that pleased almost nobody. Wealthy countries promised to deliver 300 billion dollars a year to developing nations by 2035, a significant rise from the old 100 billion target. Developing countries, which had asked for at least 500 billion, called the deal "far from enough". Their argument is simple: the poorest nations did the least to cause climate change but face its worst effects, from floods to failing harvests. The conference did make progress on other fronts, agreeing on rules for international carbon markets under the Paris Agreement. Yet critics noted that a record 1,773 fossil fuel lobbyists were registered at the summit — more than the delegations of many small countries. The gap between promises and payments remains the deepest fault line in global climate politics.`
    },
    {
        id: 'spk-australia-ban',
        tier: 'advanced',
        title: 'Australia Bans Social Media for Under-16s',
        cefr: 'B2',
        theme: '社会·未成年人社交媒体禁令',
        source: 'BBC News',
        text: `In November 2024, Australia passed the world's most sweeping law against teenage social media use. The Online Safety Amendment bans children under sixteen from platforms such as Facebook, Instagram, TikTok, Snapchat and Reddit — with no exception even for parental consent. Companies that fail to enforce the age limit face fines of up to 49.5 million Australian dollars. The law took effect in December 2025, and Meta has already begun removing accounts belonging to younger users. Supporters point to rising rates of anxiety and depression among teenagers, and argue that platforms are designed to be addictive. Critics question whether age verification can work without invading everyone's privacy, and whether the state should decide for parents. Australia is now a global experiment: if the ban improves teenage mental health, other countries may follow; if it fails, the debate will start again.`
    },
    {
        id: 'spk-crispr',
        tier: 'advanced',
        title: 'CRISPR Rewrites Medicine',
        cefr: 'C1',
        theme: '医学·首个 CRISPR 基因疗法',
        source: 'BBC News',
        text: `In December 2023, the US Food and Drug Administration approved Casgevy, the world's first therapy based on CRISPR gene editing. The treatment targets sickle cell disease and beta-thalassaemia, two inherited blood disorders caused by a single faulty gene. The procedure is extraordinary: doctors remove stem cells from the patient's own bone marrow, edit them in a laboratory to switch on a protective gene, and infuse the corrected cells back. In clinical trials, 29 of 31 patients remained free of severe pain crises for more than a year. The price, however, is breathtaking — about 2.2 million dollars in the United States. Gene therapy will never be cheap, but it offers something medicine rarely promises: a one-time cure rather than a lifetime of treatment. The first approval is a beginning, not an end; dozens of similar therapies are already in development for other genetic diseases.`
    },
    {
        id: 'spk-artemis2',
        tier: 'advanced',
        title: 'Back to the Moon: Artemis II',
        cefr: 'B2',
        theme: '航天·阿尔忒弥斯二号绕月',
        source: 'NASA / BBC',
        text: `On 1 April 2026, a spacecraft left Earth carrying four astronauts farther from our planet than anyone has travelled in over fifty years. The Artemis II mission circled the Moon and returned safely after nine days. The crew — Reid Wiseman, Victor Glover, Christina Koch and Jeremy Hansen — travelled more than 700,000 miles, reaching a record 252,756 miles from Earth, farther than even Apollo 13. The flight marked the first time since 1972 that humans have left low Earth orbit, and the first time a woman, a person of colour, and a non-American have flown around the Moon. The mission came after years of delays caused by problems with the Orion capsule's heat shield, which engineers redesigned before launch. Artemis II is a test flight; Artemis III aims to land humans on the lunar south pole. After half a century, the Moon is again within reach.`
    },
    {
        id: 'spk-neuralink',
        tier: 'advanced',
        title: 'Mind Meets Machine: Neuralink',
        cefr: 'C1',
        theme: '科技·脑机接口的进展与伦理',
        source: 'BBC News',
        text: `In January 2024, a 29-year-old man paralysed from the neck down became the first human to receive a brain implant from Neuralink. Within weeks, Noland Arbaugh was moving a cursor, playing chess and browsing the internet using only his thoughts. The technology works by reading electrical signals from a small chip implanted in the motor cortex, translating intention into action. The path was not smooth: about 85 percent of the implant's threads retracted from his brain tissue in the first months, and engineers had to restore the device's performance with software updates. By late 2025, twelve participants had received implants, logging more than 15,000 hours of use. The company, valued at roughly nine billion dollars, sees a future in which paralysis, blindness and even speech loss are addressed digitally. Ethicists, however, ask harder questions: who owns the data inside our heads, and what happens when thought itself becomes a product? The technology is advancing faster than the answers.`
    },
    {
        id: 'spk-1p5-degree',
        tier: 'advanced',
        title: '2024: The First Year Above 1.5 Degrees',
        cefr: 'C1',
        theme: '气候·2024 年突破 1.5°C',
        source: 'Copernicus',
        text: `In January 2025, the European climate service Copernicus confirmed what many had feared: 2024 was the hottest year ever recorded, and the first full calendar year to pass the 1.5-degree threshold set in the Paris Agreement. The global average temperature reached 15.10 degrees Celsius, about 1.6 degrees above pre-industrial levels. On 22 July 2024, the planet experienced its single hottest day in recorded history. Scientists are careful with their words: one year above 1.5 degrees does not mean the agreement's goal has failed, since the target refers to a long-term average over decades. Yet the trend is unmistakable. Every decade since the 1980s has been warmer than the last, and the gap is widening faster than models predicted. World Meteorological Organization estimates put the same year at 1.55 degrees, with a small margin of uncertainty. Whether the threshold is temporary or permanent, the numbers have moved beyond theory — they are now part of daily weather.`
    },
    {
        id: 'spk-deep-sea',
        tier: 'advanced',
        title: 'Deep Sea Mining: Gold Rush or Gamble?',
        cefr: 'C1',
        theme: '环境·深海采矿之争',
        source: 'BBC News',
        text: `Beneath the waves, at depths of four to six kilometres, the ocean floor is scattered with potato-sized rocks called polymetallic nodules. They contain copper, nickel, cobalt and manganese — the metals needed for batteries, phones and electric cars. In 2024, Norway became the first country to approve commercial deep-sea exploration, and companies argue that mining these nodules could supply the green transition without destroying forests on land. Scientists warn the trade-off may be worse than the problem it solves. Only about a quarter of the deep seabed has been mapped, and studies of mining test sites show that life on the ocean floor disappears for decades after the sediment settles. The International Seabed Authority has already issued 31 exploration licences across an area larger than many countries. As pressure grows to electrify everything, the deepest question is whether we can afford to extract our future at the cost of a world we barely understand.`
    },
    {
        id: 'spk-willow',
        tier: 'advanced',
        title: 'Google\'s Willow Chip: The Quantum Leap',
        cefr: 'C1',
        theme: '科技·量子计算纠错突破',
        source: 'Google Research',
        text: `On 9 December 2024, Google announced a chip called Willow that quantum physicists had waited thirty years to see. The 105-qubit processor achieved "below-threshold" error correction: adding more qubits reduced errors instead of increasing them. That breakthrough solves the central problem of quantum computing, where fragile quantum states collapse at the slightest disturbance. To demonstrate the chip's power, Google ran a calculation that would take the world's fastest supercomputer, Frontier, roughly ten to the power of twenty-five years — longer than the age of the universe. Willow finished it in under five minutes. Hartmut Neven, who leads Google's quantum team, called the moment a turning point, but he is careful about expectations. A powerful processor is not yet a useful computer; error correction must improve further before quantum machines can simulate new drugs, design better batteries or break modern encryption. The path is long, but for the first time the destination looks reachable.`
    },
    {
        id: 'spk-microplastics',
        tier: 'advanced',
        title: 'Microplastics Found in Human Brains',
        cefr: 'C1',
        theme: '健康·大脑中的微塑料研究',
        source: 'Nature Medicine',
        text: `A study published in Nature Medicine in 2025 delivered one of the most unsettling findings in environmental health: microplastics are accumulating in human brains. Researchers at the University of New Mexico analysed brain tissue from autopsies and found that median plastic concentrations rose from about 3,345 micrograms per gram in 2016 to nearly 4,917 by 2024 — an increase of roughly fifty percent in eight years. The brain contained ten to twenty times more plastic than the liver or kidneys, amounting to about half a percent of the organ's weight. The dominant material was polyethylene, the plastic of shopping bags and food containers. The researchers, led by Matthew Campen, were careful to say that the study does not prove microplastics cause disease. But the finding raises questions scientists cannot yet answer: how do plastic particles cross the blood-brain barrier, and what happens when they settle there? While the debate continues, the particles themselves are already inside us.`
    }
];
